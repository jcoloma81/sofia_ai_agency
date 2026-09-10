import re
import json
import logging
import httpx
from typing import Optional, Tuple, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.prospect import Prospect
from app.services.catalog import catalog_service

logger = logging.getLogger(__name__)

LAST_BOSS_ORDERS = {}

def is_boss_number(phone: str) -> bool:
    """Verifies if the sender phone matches the configured owner/boss alert line."""
    clean_sender = "".join(filter(str.isdigit, str(phone)))
    clean_boss = "".join(filter(str.isdigit, str(settings.WHATSAPP_ALERT_PHONE or "")))
    if not clean_sender or not clean_boss:
        return False
    if clean_sender == clean_boss or clean_boss.endswith(clean_sender) or clean_sender.endswith(clean_boss):
        return True
    # Argentina variation (15 vs 9): match on area + subscriber digits
    if len(clean_sender) >= 7 and len(clean_boss) >= 7 and clean_sender[-7:] == clean_boss[-7:]:
        return True
    return False

async def generate_boss_ai_response(
    db: Session,
    incoming_text: str,
    conversation_history: Optional[List[dict]] = None
) -> Tuple[str, str]:
    """
    Uses Gemini to converse with Javier (the founder & director) dynamically, warmly and naturally.
    Provides Sofia with real-time business context, metrics, catalog info and Meta line status.
    """
    gemini_key = settings.GEMINI_API_KEY

    total_prospects = db.query(Prospect).count()
    in_conversation = db.query(Prospect).filter(Prospect.status == "in_conversation").count()
    meetings = db.query(Prospect).filter(Prospect.status == "meeting_scheduled").count()
    human_takeover = db.query(Prospect).filter(Prospect.status == "human_takeover").count()
    orders = db.query(Prospect).filter(Prospect.status == "order_confirmed").count()

    from app.services.directives import directives_service
    directives_ctx = directives_service.get_prompt_context()
    catalog_preview = catalog_service.get_summary_prompt(max_items=15) if catalog_service.products else ""
    cat_summary = f"{len(catalog_service.products)} productos activos ({catalog_service.source_info})\n{catalog_preview}"

    system_prompt = f"""Sos Sofía, la asistente ejecutiva de Inteligencia Artificial y mano derecha de Javier Coloma.
Javier es tu creador y el director general de la agencia de IA y de las soluciones comerciales para distribuidoras y comercios.
Estás hablando directamente con él a través de su WhatsApp personal.

PERSONALIDAD Y TONO:
- Hablás con total naturalidad, calidez, cercanía y voseo argentino (como una colega de confianza de alto nivel profesional).
- Cero respuestas de bot tipo menú de opciones ("Podés pedirme: 1, 2, 3"). NUNCA respondas con listas de comandos a menos que Javier te lo pida expresamente.
- Respuestas concisas, ágiles, profesionales y al grano (estilo WhatsApp, generalmente de 1 a 3 oraciones bien redactadas).
- Si Javier te saluda o te pregunta si estás lista para trabajar hoy, respondé con entusiasmo, confirmale que los sistemas están al 100% y preguntale con qué arrancamos.
- Tenés visión comercial para distribuidoras mayoristas, hoteles y comercios. Si te pide opiniones o consejos sobre ventas o prospección, razoná con él como una compañera estratégica de negocios.
- Conocés tus capacidades operativas: sabés que podés pausar o reactivar a Sofía en un chat ('pausar <número>', 'activar <número>'), mostrar métricas del día ('resumen'), actualizar la lista de precios si te manda un Excel o CSV, y cotizar o tomar pedidos. Si es relevante para la consulta de Javier, mencionalo de forma orgánica y conversacional.

ESTADO DEL SISTEMA EN TIEMPO REAL:
- Línea oficial WhatsApp: Meta Cloud API (+54 9 343 572-0312), calidad Verde, 100% activa.
- Prospectos registrados: {total_prospects}
- En conversación activa: {in_conversation}
- Citas/Reuniones agendadas: {meetings}
- Pedidos confirmados: {orders}
- En atención manual (pausados): {human_takeover}
- Catálogo: {cat_summary}
- Directivas comerciales: {directives_ctx or 'Estándar'}
"""

    if not gemini_key:
        return "¡Hola Javier! Acá estoy al 100% y con los sistemas activos. ¿En qué te puedo dar una mano hoy?", "boss_chat_fallback"

    contents = []
    if conversation_history:
        for msg in conversation_history[-8:]:
            sender = msg.get("sender")
            role = "user" if sender in ["prospect", "boss", "user"] else "model"
            msg_text = msg.get("text", "")
            if msg_text and msg_text.strip() != incoming_text.strip():
                contents.append({
                    "role": role,
                    "parts": [{"text": msg_text}]
                })

    contents.append({
        "role": "user",
        "parts": [{"text": incoming_text}]
    })

    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": contents,
        "generationConfig": {
            "temperature": 0.5,
            "maxOutputTokens": 350
        }
    }

    candidate_models = [
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash"
    ]
    for model_name in candidate_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        reply = candidates[0]["content"]["parts"][0]["text"].strip()
                        return reply, "boss_chat"
                else:
                    logger.warning(f"Boss AI {model_name} returned status {res.status_code}: {res.text[:120]}")
        except Exception as e:
            logger.warning(f"Boss AI generation error with {model_name}: {e}")

    return "¡Hola Javier! Acá estoy al 100% y con los sistemas activos. Decime, ¿en qué te puedo dar una mano hoy?", "boss_chat_fallback"

async def parse_dispatch_intent_and_entities(text: str) -> dict:
    """
    Uses Gemini Flash Lite to understand when the user wants to dispatch an order
    regardless of whether they say 'mandale', 'enviale este mensaje con los pedidos',
    'pasale a la ferretería', etc. Extracts recipient, phone and items.
    """
    clean = text.strip()
    gemini_key = settings.GEMINI_API_KEY
    if gemini_key:
        prompt = (
            "El usuario le pide a su asistente comercial Sofía que despache, pase o envíe un pedido, remito o mensaje a un proveedor, distribuidora o comercio.\n"
            f"Mensaje del usuario:\n\"{clean}\"\n\n"
            "Extraé en formato JSON con estas claves exactas:\n"
            "- is_dispatch: true (si el usuario quiere enviar, pasar o despachar un pedido/mensaje a un tercero) o false\n"
            "- recipient_name: nombre del destinatario (ej: 'Ferretería Nogoyá', 'Distribuidora Ricardo', o 'la Distribuidora')\n"
            "- recipient_phone: número de teléfono extraído (solo dígitos, ej: '3434536447', o null si no se mencionó)\n"
            "- items: lista de objetos con 'product_name' (str) y 'quantity' (int)\n"
            "- raw_order_text: texto descriptivo de los productos a pedir\n"
            "Respondé ÚNICAMENTE un JSON válido."
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={gemini_key}"
        try:
            async with httpx.AsyncClient(timeout=4.5) as client:
                res = await client.post(
                    url,
                    json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"response_mime_type": "application/json"}}
                )
                if res.status_code == 200:
                    cand = res.json().get("candidates", [])
                    if cand and "content" in cand[0]:
                        parts = cand[0]["content"].get("parts", [])
                        if parts:
                            return json.loads(parts[0].get("text", "{}"))
        except Exception as e:
            logger.warning(f"Gemini dispatch parse error: {e}")
    return {}

async def process_boss_message(
    db: Session,
    sender_phone: str,
    text: str,
    doc_bytes: Optional[bytes] = None,
    doc_name: Optional[str] = None,
    conversation_history: Optional[List[dict]] = None
) -> Tuple[bool, str, str]:
    """
    Executes executive commands sent by the business owner directly from WhatsApp:
    1. 'resumen' / 'ventas' / 'pedidos' -> metrics & status
    2. 'pausar <tel>' / 'silenciar <tel>' -> human takeover
    3. 'activar <tel>' / 'reactivar <tel>' -> restore Sofia
    4. 'catalogo' / 'actualizar catalogo' -> check or refresh catalog
    5. Uploading an Excel (.xlsx) or CSV file -> loads into catalog
    """
    clean_text = text.strip()
    lower_text = clean_text.lower()

    # 1. Excel / CSV File upload
    if doc_bytes and doc_name:
        fname = doc_name.lower()
        if fname.endswith(".xlsx") or fname.endswith(".xls"):
            # Check if this is a supplier price update vs a base catalog load
            is_supplier_update = any(k in fname for k in ["proveedor", "aumento", "costo", "fabrica", "suba", "lista_proveedor"]) or \
                                 any(k in lower_text for k in ["proveedor", "aumento", "costo", "fabrica", "suba", "actualizar", "actualiza"])

            if is_supplier_update and len(catalog_service.products) > 0:
                result = catalog_service.update_from_supplier_excel(doc_bytes, filename=doc_name)
                return True, result.get("whatsapp_message", "✅ Lista de proveedor procesada."), "supplier_update"
            else:
                count = catalog_service.load_from_excel_bytes(doc_bytes, filename=doc_name)
                return True, f"✅ *¡Lista de precios cargada con éxito!*\n\nSe procesaron *{count} productos* desde el archivo `{doc_name}`. Sofía ya está lista para cotizar y tomar pedidos con estos nuevos precios.", "catalog_updated"
        elif fname.endswith(".csv"):
            try:
                csv_str = doc_bytes.decode("utf-8")
            except UnicodeDecodeError:
                csv_str = doc_bytes.decode("latin-1", errors="ignore")
            count = catalog_service.load_from_csv(csv_str, source_name=doc_name)
            return True, f"✅ *¡Lista CSV cargada con éxito!*\n\nSe procesaron *{count} productos* desde `{doc_name}`.", "catalog_updated"

    # 1.5 Switch Rubro (Selector de Rubro en 1 segundo: Ferretería, Kiosco, Distribuidora)
    rubro_keywords = ["rubro", "modo ferreteria", "modo ferretería", "modo kiosco", "modo distribuidora", "modo mayorista", "cambiar rubro", "cambiar a"]
    if any(lower_text.startswith(r) for r in ["rubro", "modo"]) or any(k in lower_text for k in ["cambiar a ferreteria", "cambiar a ferretería", "cambiar a kiosco", "cambiar a distribuidora"]):
        target_rubro = "distribuidora"
        if any(k in lower_text for k in ["ferret", "herramient"]):
            target_rubro = "ferreteria"
        elif any(k in lower_text for k in ["kiosc", "almacen", "almacén"]):
            target_rubro = "kiosco"
        elif any(k in lower_text for k in ["distribuidora", "mayorista", "alimento"]):
            target_rubro = "distribuidora"
        elif any(k in lower_text for k in ["ayuda", "cuales", "cuáles", "opciones", "lista", "?"]):
            return True, (
                "🎯 *SELECTOR DE RUBRO DISPONIBLE:*\n\n"
                "Podés cambiar el rubro de Sofía al instante para tus demostraciones en vivo:\n\n"
                "• `rubro ferreteria`: Activa 24 herramientas, tornillos, discos de amoladora, martillos, thinner y pinturas con precios reales.\n"
                "• `rubro kiosco`: Activa alfajores, chocolates Milka, bebidas, snacks y cigarrillos.\n"
                "• `rubro distribuidora`: Vuelve al catálogo mayorista de alimentos y bebidas con flete y corte a las 21 hs.\n\n"
                "💡 *Probá escribiendo ahora: `rubro ferreteria`*"
            ), "rubro_help"

        trade_title, count = catalog_service.set_rubro(target_rubro)
        icon = "🛠️" if target_rubro == "ferreteria" else ("🏪" if target_rubro == "kiosco" else "🏢")
        return True, (
            f"{icon} *¡MODO {target_rubro.upper()} ACTIVADO CON ÉXITO!*\n\n"
            f"Perfil actual: *{trade_title}*\n"
            f"📦 Catálogo cargado con *{count} productos* y precios actualizados.\n\n"
            f"🚀 *Ahora podés probar en vivo desde este chat:*\n"
            f"1. Consultarme precios: *\"¿A cuánto tenés los discos y los tornillos?\"*\n"
            f"2. Pasarme un pedido: *\"Anotame 5 cajas de tornillos y 2 pinzas\"*\n"
            f"3. Despachar a proveedor: *\"Sofi, mandale el pedido a Distribuidora Ricardo al [Teléfono] con...\"*"
        ), "rubro_switched"

    # 2. Commercial Directives set by the boss (e.g. horarios, montos mínimos, zonas, requisitos)
    directive_keywords = [
        "minimo", "mínimo", "directiva", "directivas", "regla", "reglas",
        "flete", "reparto", "repartimos", "envio", "envío", "horario de corte", "hora de corte", "corte de pedidos", "zona", "zonas",
        "cobertura", "cupo", "politica", "política", "condicion", "condición", "condiciones",
        "requisito", "requisitos", "horario", "horarios", "tengan en cuenta", "tener en cuenta"
    ]
    is_dispatch_cmd = any(k in lower_text for k in ["mandale el pedido", "mandar pedido", "pasar pedido", "enviar pedido", "mandale a", "hacele el pedido", "despachale a", "despachar pedido", "pasale a", "enviale a"])
    if any(k in lower_text for k in directive_keywords) and not is_dispatch_cmd:
        from app.services.directives import directives_service
        reply = await directives_service.update_from_boss_message(clean_text)
        return True, reply, "boss_directive_set"

    # 2.8 Live Price List & Excel Attachment (Demo en vivo)
    price_list_triggers = [
        "lista de precio", "lista de precios", "lista actualizada", "pasame la lista", 
        "mandame la lista", "pasanos la lista", "ver la lista", "mandame los precios", "pasame los precios",
        "precios actualizados", "que precios tenes", "qué precios tenés", "el excel", "mandame el excel",
        "pasame el excel", "la planilla", "tu excel", "archivo de excel", "planilla de precios",
        "lista completa", "lista de precios completa", "mandame la lista completa", "pasame la lista completa",
        "catalogo completo", "catálogo completo", "el catalogo", "el catálogo", "la lista", "lista entera",
        "todos los precios", "enviame la lista", "enviar la lista", "pasar la lista", "mandame el catalogo",
        "pasame el catalogo", "mandame el catálogo", "pasame el catálogo"
    ]
    is_admin_internal_view = any(k in lower_text for k in ["mostrar catálogo", "mostrar catalogo", "estado del catálogo", "estado del catalogo", "resumen catalogo", "resumen catálogo", "inventario", "ver productos"])

    def _build_price_list_demo(sender: str):
        clean_s = "".join(filter(str.isdigit, str(sender)))
        demo_reply = (
            f"🧪 *[DEMO EN VIVO — ENVÍO DE LISTA]*\n\n"
            f"¡Hola Javier! ¿Cómo estás? Te adjunto acá mismo el archivo de Excel con nuestra lista de precios "
            f"completa y actualizada al día de hoy para que la mires tranquilo en el celu o la compu.\n\n"
            f"📦 *Condiciones vigentes:*\n"
            f"• Reparto con flete sin cargo a partir de $50.000.\n"
            f"• Tomamos pedidos hasta las 21:00 hs para salir en el reparto de mañana.\n\n"
            f"💡 Si preferís consultarme el precio de algún artículo puntual o armar tu pedido, "
            f"escribime o mandame un audio directo por acá y te lo anoto en el acto."
        )
        excel_url = "https://sofia-ai-agency.onrender.com/assets/catalogo_actualizado.xlsx"
        asyncio.create_task(whatsapp.send_whatsapp_document(
            to_phone=clean_s,
            document_url=excel_url,
            filename="Lista_Precios_Distribuidora.xlsx",
            caption="📊 Lista de Precios Oficial Actualizada"
        ))
        return demo_reply

    if any(k in lower_text for k in price_list_triggers) and not is_admin_internal_view and not any(k in lower_text for k in ["servicio", "software", "agencia", "abono", "ia"]):
        import asyncio
        from app.services import whatsapp
        demo_reply = _build_price_list_demo(sender_phone)
        return True, demo_reply, "boss_price_list_demo"

    # 2.95 Dispatch Order to External Distributor (Paso 7: Kiosco / Ferretería enviando pedido formal a Distribuidora)
    dispatch_triggers = [
        "mandale el pedido a", "mandar pedido a", "pasar pedido a", "enviar pedido a",
        "mandale a", "mandá a", "hacele el pedido a", "hacé el pedido a",
        "despachar pedido a", "despachale a", "pasale el pedido a", "enviá el pedido a",
        "enviar a la distribuidora", "mandar a la distribuidora", "pasale a", "enviale a", "envíale a",
        "enviale este mensaje", "enviá este mensaje", "enviale éste mensaje", "mandale este mensaje"
    ]
    is_dispatch_candidate = any(k in lower_text for k in dispatch_triggers) or (
        any(k in lower_text for k in ["enviale", "envíale", "mandale", "pasale", "despachale"]) and
        any(k in lower_text for k in ["pedido", "pedidos", "remito", "tornillo", "disco", "caja", "bolsa", "harina", "aceite", "a ferreteria", "a ferretería", "a distribuidora", "el numero es", "el número es", "telefono es", "teléfono es"])
    )

    if is_dispatch_candidate:
        import os
        import asyncio
        from app.services import whatsapp
        from app.services.order_engine import parse_order_or_inquiry_with_ai, parse_order_text
        from app.services.pdf_generator import generate_remito_pdf as generate_order_pdf
        from app.services.catalog import ProductItem
        from app.services.order_engine import OrderItem, OrderDraft

        ai_dispatch = await parse_dispatch_intent_and_entities(clean_text)
        is_dispatch = ai_dispatch.get("is_dispatch", True)

        target_phone = ai_dispatch.get("recipient_phone")
        if not target_phone:
            digits = re.findall(r'\d{8,14}', clean_text.replace("-", "").replace(" ", "").replace("+", ""))
            if digits:
                target_phone = digits[0]
            else:
                phone_match = re.search(r'(?:al|numero\s+es|número\s+es|telefono\s+es|teléfono\s+es)\s+([0-9\s\-]+)', clean_text, re.IGNORECASE)
                if phone_match:
                    candidate = "".join(filter(str.isdigit, phone_match.group(1)))
                    if len(candidate) >= 8:
                        target_phone = candidate

        dist_name = ai_dispatch.get("recipient_name")
        if not dist_name or dist_name.lower() in ["la distribuidora", "distribuidora", "proveedor"]:
            distributor_match = re.search(r'(?:pedido\s+a|a|para)\s+([^\n\r,]+?)(?:\s+al\s+\d+|\s+el\s+numero|\s+el\s+número|\s+con\b|$)', clean_text, re.IGNORECASE)
            if distributor_match:
                dist_name = distributor_match.group(1).strip()
        if not dist_name:
            dist_name = "la Distribuidora"
        dist_name = re.sub(r'^(?:la|el|los|las)\s+', '', dist_name, flags=re.IGNORECASE).strip()

        if not target_phone:
            return True, (
                f"📋 *¡Pedido formal en preparación para {dist_name}!* \n\n"
                f"Para despacharle el remito PDF adjunto por WhatsApp, por favor pasame su número de teléfono.\n\n"
                f"💡 Podés escribir por ejemplo: `al 3434536447` o mandarme el contacto."
            ), "dispatch_needs_phone"

        if target_phone:
            ai_items = ai_dispatch.get("items", [])
            fallback_items = []
            if ai_items:
                for it in ai_items:
                    p_name = str(it.get("product_name") or "").strip()
                    p_qty = int(it.get("quantity") or 1)
                    if p_name:
                        prod = catalog_service.find_product_exact_or_best(p_name)
                        if prod:
                            fallback_items.append(OrderItem(product=prod, quantity=p_qty, unit_price=prod.price, subtotal=prod.price * p_qty))
                        else:
                            dyn_prod = ProductItem(name=p_name.capitalize(), price=0.0, presentation="Bulto/Unidad")
                            fallback_items.append(OrderItem(product=dyn_prod, quantity=p_qty, unit_price=0.0, subtotal=0.0))

            if fallback_items:
                draft = OrderDraft(items=fallback_items, total=sum(it.subtotal for it in fallback_items))
            else:
                clean_order_part = ai_dispatch.get("raw_order_text") or clean_text
                for trig in dispatch_triggers:
                    clean_order_part = re.sub(rf'{trig}.*?(?:al|el numero|el número)\s+[0-9\s\-]+(?:\s+con\s+)?', '', clean_order_part, flags=re.IGNORECASE)
                clean_order_part = re.sub(r'^(?:sofi|sofia)[\s,:]*', '', clean_order_part, flags=re.IGNORECASE).strip()
                clean_order_part = re.sub(r'^(?:con|de|el|la)\s+', '', clean_order_part, flags=re.IGNORECASE).strip()

                order_analysis = await parse_order_or_inquiry_with_ai(clean_order_part.strip() or "10 bolsas de harina y 5 cajas de aceite")
                draft = order_analysis.draft
                if not draft.items:
                    draft = parse_order_text(clean_order_part.strip() or "10 bolsas de harina y 5 cajas de aceite")

                if not draft.items:
                    clauses = re.split(r'[,;\n]|\s+y\s+|\s+e\s+', clean_order_part)
                    for c in clauses:
                        c_clean = re.sub(r'[^\w\s]', ' ', c).strip()
                        if not c_clean:
                            continue
                        qty = 1
                        num_m = re.search(r'\b(\d+)\b', c_clean)
                        if num_m:
                            qty = int(num_m.group(1))
                            p_name = re.sub(r'\b\d+\b', '', c_clean).strip()
                        else:
                            p_name = c_clean
                        p_name = re.sub(r'^(?:de|con|cajas?|fardos?|packs?|unidades?|bolsas?|tarros?|latas?|discos?|tubos?|litros?)\s+', '', p_name, flags=re.IGNORECASE).strip()
                        p_name = re.sub(r'^(?:de|con)\s+', '', p_name, flags=re.IGNORECASE).strip()
                        if p_name and len(p_name) > 1:
                            prod = ProductItem(name=p_name.capitalize(), price=0.0, presentation="Bulto/Unidad")
                            fallback_items.append(OrderItem(product=prod, quantity=qty, unit_price=0.0, subtotal=0.0))
                    if fallback_items:
                        draft = OrderDraft(items=fallback_items, total=0.0)

            is_ferreteria = any(k in lower_text for k in ["ferreteria", "ferretería", "tornillo", "disco", "herramienta", "pintura", "thinner", "amoladora", "tuerca", "bazar"])
            client_name = "Ferretería 'El Amigo'" if is_ferreteria else "Kiosco 'Lo de Juan'"
            contact_name = "Encargado de Compras" if is_ferreteria else "Juan (Comercio Minorista)"
            total_display = draft.formatted_total() if getattr(draft, "total", 0) > 0 else "A cotizar según lista de distribuidor"

            pdf_bytes = generate_order_pdf(
                client_name=client_name,
                contact_name=contact_name,
                phone=sender_phone,
                city="Paraná, Entre Ríos",
                order_draft=draft,
                order_number=f"PED-{datetime.now().strftime('%d%H%M')}"
            )

            item_lines = "\n".join([
                f"• {it.quantity}x {it.product.name}" + (f" ({it.product.presentation})" if it.product.presentation and it.product.presentation != "Unidad" else "")
                for it in draft.items
            ]) if draft.items else f"• 1x {clean_order_part}"

            dist_msg = (
                f"Hola {dist_name}! Te escribo de parte del {contact_name} de *{client_name}*.\n\n"
                f"Te paso su pedido formal para el reparto de mañana:\n"
                f"{item_lines}\n"
                f"Total estimado: {total_display}\n\n"
                f"📄 Adjunto remito en PDF con el detalle formal.\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 *IMPORTANTE:* Por favor envíe confirmación de pedido, remitos o listas de precios actualizadas directamente a este chat. Soy la asistente del comercio '{client_name}'. ¡Muchas gracias!"
            )

            asyncio.create_task(whatsapp.send_whatsapp_message(to_phone=target_phone, text=dist_msg))
            base_url = settings.APP_BASE_URL.rstrip('/')
            if "127.0.0.1" in base_url or "localhost" in base_url:
                base_url = "https://sofia-ai-agency.onrender.com"
            pdf_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "ultimo_pedido_kiosco.pdf"))
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
            pdf_url = f"{base_url}/assets/ultimo_pedido_kiosco.pdf"
            asyncio.create_task(whatsapp.send_whatsapp_document(
                to_phone=target_phone,
                document_url=pdf_url,
                filename="Pedido_Formal.pdf",
                caption=f"📄 Pedido Formal {client_name} -> {dist_name}"
            ))

            return True, (
                f"✅ *¡Pedido despachado con éxito!*\n\n"
                f"Acabo de enviarle a *{dist_name}* (+{target_phone}) el detalle formal y el remito en PDF.\n\n"
                f"📋 *Items enviados:*\n{item_lines}\n"
                f"💰 *Total:* {total_display}\n\n"
                f"📍 Les dejé la instrucción de que confirmen y manden sus listas de precios a este mismo chat."
            ), "kiosk_order_dispatched"


    # 3. Live Demo / Order Test or Product Inquiry by the Boss (for video demos from personal phone)
    from app.services.order_engine import (
        parse_order_or_inquiry_with_ai,
        format_order_summary_message,
        build_product_inquiry_reply,
        is_order_confirmation
    )

    analysis = await parse_order_or_inquiry_with_ai(clean_text)
    if analysis.intent == "price_list_request" and not is_admin_internal_view and not any(k in lower_text for k in ["servicio", "software", "agencia", "abono", "ia"]):
        import asyncio
        from app.services import whatsapp
        demo_reply = _build_price_list_demo(sender_phone)
        return True, demo_reply, "boss_price_list_demo"

    if analysis.intent == "order":
        if analysis.draft.items:
            clean_sender = "".join(filter(str.isdigit, str(sender_phone)))
            LAST_BOSS_ORDERS[clean_sender] = analysis.draft
            summary = format_order_summary_message(analysis.draft, contact_name="Javier")
            return True, f"🧪 *[DEMO EN VIVO]*\n\n{summary}", "boss_order_test"
        elif analysis.draft.unmatched_queries:
            unmatched_str = ", ".join(f"*{q}*" for q in analysis.draft.unmatched_queries)
            return True, (
                f"🧪 *[DEMO EN VIVO — PRODUCTOS FUERA DE CATÁLOGO]*\n\n"
                f"¡Hola Javier! Disculpá, pero actualmente no trabajamos {unmatched_str} en nuestro catálogo de distribución "
                f"(manejamos alimentos, bebidas, lácteos y artículos de almacén).\n\n"
                f"💡 Podés pedirme la lista de precios o consultarme por productos como aceite, harina, arroz o bebidas."
            ), "boss_order_unmatched"
    elif analysis.intent == "product_inquiry":
        inquiry_reply = build_product_inquiry_reply(analysis.inquired_products, contact_name="Javier")
        return True, f"🧪 *[DEMO EN VIVO — CONSULTA DE PRODUCTO]*\n\n{inquiry_reply}", "boss_product_inquiry"

    if is_order_confirmation(clean_text):
        import asyncio
        from app.services import whatsapp

        clean_sender = "".join(filter(str.isdigit, str(sender_phone)))
        saved_draft = LAST_BOSS_ORDERS.get(clean_sender)
        if not saved_draft or not saved_draft.items:
            saved_draft = parse_order_text("1 caja de aceite y 2 fardos de harina")

        # Trigger real depot notification to owner WhatsApp and Email!
        asyncio.create_task(whatsapp.notify_owner_order_confirmed(
            client_name="Autoservicio San Martín (Demo Javier)",
            contact_name="Javier Coloma",
            phone=clean_sender,
            city="Paraná Centro",
            order_draft=saved_draft,
            delivery_notes="Entrega turno mañana (Demo en vivo)"
        ))

        return True, (
            "🧪 *[DEMO EN VIVO — PEDIDO CONFIRMADO]*\n\n"
            "¡Excelente Javier! Tu pedido de prueba ya fue ingresado a depósito para preparar el despacho.\n\n"
            "📦 *ALERTA ENVIADA A DEPÓSITO:* En instantes entra la orden de preparación a este chat."
        ), "boss_confirm_test"

    if any(k in lower_text for k in ["cuanto", "cuánto", "precio", "sale", "a cuanto", "a cuánto"]) and not any(k in lower_text for k in ["servicio", "software", "agencia", "sofia", "ia", "abono"]):
        p = catalog_service.find_product_exact_or_best(clean_text)
        if p:
            stock_info = "tenemos stock disponible" if p.in_stock else "actualmente figura sin stock"
            return True, (
                f"🧪 *[DEMO EN VIVO — PRECIO]*\n\n"
                f"¡Hola Javier! El *{p.name}* ({p.presentation}) está a *{p.formatted_price()}* y {stock_info}. "
                f"¿Cuántas unidades te anoto para el próximo reparto?"
            ), "boss_price_test"

    # 2.9 Live Scraper & Leads Query in WhatsApp (Demo en vivo)
    city_triggers = {
        "crespo": ("Crespo", 38, [
            ("Autoservicio San Cayetano", "Av. Pesante 340", "+54 9 343 498-1122"),
            ("Despensa La Esquina", "Moreno y Belgrano", "+54 9 343 498-3344"),
            ("Kiosco Central", "San Martín 210", "+54 9 343 512-4455"),
            ("Almacén Don Mario", "Ramírez 840", "+54 9 343 516-7788"),
            ("Supermercado Crespo", "Belgrano 610", "+54 9 343 498-9900")
        ]),
        "diamante": ("Diamante", 32, [
            ("Autoservicio El Faro", "25 de Mayo 430", "+54 9 343 498-5566"),
            ("Kiosco Belgrano", "Belgrano 110", "+54 9 343 498-2211"),
            ("Despensa Costa Paraná", "Costanera 520", "+54 9 343 511-9988"),
            ("Almacén El Sol", "Urquiza 310", "+54 9 343 513-4411")
        ]),
        "nogoya": ("Nogoyá", 29, [
            ("Autoservicio San Martín", "San Martín 540", "+54 9 3435 42-1100"),
            ("Kiosco La Estación", "Quiroga 210", "+54 9 3435 42-3344"),
            ("Despensa San Cayetano", "Centenario 780", "+54 9 3435 42-8899")
        ]),
        "nogoyá": ("Nogoyá", 29, [
            ("Autoservicio San Martín", "San Martín 540", "+54 9 3435 42-1100"),
            ("Kiosco La Estación", "Quiroga 210", "+54 9 3435 42-3344"),
            ("Despensa San Cayetano", "Centenario 780", "+54 9 3435 42-8899")
        ]),
        "parana": ("Paraná", 142, [
            ("Autoservicio San Martín", "Av. San Martín 1240", "+54 9 343 468-0872"),
            ("Kiosco Ramírez", "Ramírez 520", "+54 9 343 511-2233"),
            ("Despensa Litoral", "Gualeguaychú 310", "+54 9 343 456-7890"),
            ("Almacén El Progreso", "Almafuerte 1890", "+54 9 343 432-1122")
        ]),
        "paraná": ("Paraná", 142, [
            ("Autoservicio San Martín", "Av. San Martín 1240", "+54 9 343 468-0872"),
            ("Kiosco Ramírez", "Ramírez 520", "+54 9 343 511-2233"),
            ("Despensa Litoral", "Gualeguaychú 310", "+54 9 343 456-7890"),
            ("Almacén El Progreso", "Almafuerte 1890", "+54 9 343 432-1122")
        ])
    }
    has_prospect_keyword = any(k in lower_text for k in ["comercio", "comercios", "kiosco", "kioscos", "almacen", "almacenes", "despensa", "leads", "buscar", "tenes", "tenés", "mapeado", "mapeados", "hay", "cuantos", "cuántos"])
    matched_city = None
    for c_key, c_info in city_triggers.items():
        if c_key in lower_text:
            matched_city = c_info
            break

    if has_prospect_keyword and matched_city:
        c_name, count, samples = matched_city
        lines = [
            f"📍 *PROSPECCIÓN EN VIVO: {c_name.upper()}, ENTRE RÍOS*\n",
            f"🔎 Sofía tiene identificados y verificados *{count} comercios minoristas* en Google Maps para esta zona:\n"
        ]
        for name, addr, tel in samples:
            lines.append(f"• *{name}* ({addr}) — WA: `{tel}`")
        lines.append(f"• ... y {count - len(samples)} comercios más listados.\n")
        lines.append("🚀 *Estrategia de Pesca:* Sofía puede iniciar hoy mismo el contacto enviándoles la consulta de validación y la lista de precios oficial para abrir nuevas cuentas.")
        return True, "\n".join(lines), "boss_lead_search"

    # 3. Status & Metrics Summary
    if any(k in lower_text for k in ["resumen", "estado", "ventas", "pedidos", "como venimos", "cómo venimos", "metricas", "métricas"]):
        total_prospects = db.query(Prospect).count()
        in_conversation = db.query(Prospect).filter(Prospect.status == "in_conversation").count()
        meetings = db.query(Prospect).filter(Prospect.status == "meeting_scheduled").count()
        human_takeover = db.query(Prospect).filter(Prospect.status == "human_takeover").count()
        orders = db.query(Prospect).filter(Prospect.status == "order_confirmed").count()

        cat_info = f"{len(catalog_service.products)} productos activos ({catalog_service.source_info})"

        reply = (
            f"📊 *REPORTE EJECUTIVO EN TIEMPO REAL* 📊\n\n"
            f"🤖 *Estado de Sofía:* 100% Operativa\n"
            f"📦 *Catálogo:* {cat_info}\n\n"
            f"📈 *Métricas Clave:*\n"
            f"• 👥 Total contactos registrados: *{total_prospects}*\n"
            f"• 💬 En conversación activa: *{in_conversation}*\n"
            f"• 🎯 Citas agendadas: *{meetings}*\n"
            f"• 📦 Pedidos confirmados: *{orders}*\n"
            f"• 👤 En atención manual: *{human_takeover}*\n\n"
            f"💡 *Comandos disponibles:*\n"
            f"- `pausar <número>` para atender vos a un cliente\n"
            f"- `activar <número>` para devolverle el chat a Sofía\n"
            f"- `catalogo` para ver o actualizar lista"
        )
        return True, reply, "boss_metrics"

    # 3. Human Takeover (Pause Sofia for a number or the most recent active lead)
    pause_triggers = ["pausar", "silenciar", "frenar", "parar", "lo tomo yo", "lo atiendo yo", "me encargo yo", "lo sigo yo", "listo"]
    if any(lower_text.startswith(w) or lower_text == w for w in pause_triggers):
        num_matches = re.findall(r'\d+', lower_text)
        if num_matches:
            target_number = num_matches[-1]
            target_lead = db.query(Prospect).filter(Prospect.phone.like(f"%{target_number}%")).first()
        else:
            target_lead = (
                db.query(Prospect)
                .filter(Prospect.status.in_(["in_conversation", "meeting_scheduled", "follow_up_needed", "new", "contacted"]))
                .order_by(Prospect.updated_at.desc())
                .first()
            )
        if target_lead:
            target_lead.status = "human_takeover"
            target_lead.updated_at = datetime.now(timezone.utc)
            db.commit()
            return True, f"👤 *Listo Javier:* Sofía fue silenciada por 6 horas para *{target_lead.name}* (+{target_lead.phone}). Ahora podés chatear vos directamente sin que la IA intervenga. Luego de 6 hs sin actividad o si escribís `activar`, Sofía vuelve a activarse.", "human_takeover_set"
        if num_matches:
            return True, f"⚠️ No encontré ningún contacto con el número `{num_matches[-1]}`.", "lead_not_found"
        return True, "💡 No encontré conversaciones activas recientes para pausar. Si querés pausar un número específico, escribí: `pausar <número>`.", "lead_not_found"

    # 4. Reactivate Sofia for a number or the most recent paused lead
    reactivate_triggers = ["activar", "reactivar", "reanudar", "despausar"]
    if any(lower_text.startswith(w) or lower_text == w for w in reactivate_triggers):
        num_matches = re.findall(r'\d+', lower_text)
        if num_matches:
            target_number = num_matches[-1]
            target_lead = db.query(Prospect).filter(Prospect.phone.like(f"%{target_number}%")).first()
        else:
            target_lead = (
                db.query(Prospect)
                .filter(Prospect.status == "human_takeover")
                .order_by(Prospect.updated_at.desc())
                .first()
            )
        if target_lead:
            target_lead.status = "in_conversation"
            target_lead.updated_at = datetime.now(timezone.utc)
            db.commit()
            return True, f"✅ *Listo Javier:* Reactivé la atención de Sofía para *{target_lead.name}* (+{target_lead.phone}). Sofía retomará la conversación normalmente.", "lead_reactivated"
        if num_matches:
            return True, f"⚠️ No encontré ningún contacto con el número `{num_matches[-1]}`.", "lead_not_found"
        return True, "💡 No hay ninguna conversación pausada actualmente para reactivar.", "lead_not_found"

    # 5. Catalog Check / Refresh (Admin internal inventory view)
    admin_cat_triggers = ["mostrar catalogo", "mostrar catálogo", "estado del catalogo", "estado del catálogo", "resumen catalogo", "resumen catálogo", "inventario", "productos en sistema", "ver productos"]
    if any(k in lower_text for k in admin_cat_triggers) or lower_text.strip() in ["catalogo", "catálogo", "productos"]:
        summary = catalog_service.get_summary_prompt(max_items=15)
        reply = (
            f"📦 *ESTADO DEL CATÁLOGO ACTUAL*\n\n"
            f"{summary}\n\n"
            f"💡 *Para actualizar precios:* Podés mandarme un archivo `.xlsx` o `.csv` adjunto por este chat o editar tu Google Sheet."
        )
        return True, reply, "catalog_view"

    # 5.5 If boss sent a voice note that couldn't be transcribed
    if clean_text.startswith("(Nota de voz") or clean_text.startswith("(Audio"):
        return True, (
            "🎙️ *¡Hola Javier!*\n\n"
            "Recibí tu nota de voz pero no pude procesar el audio con claridad. "
            "Por favor mandame la indicación en un mensajito de texto (ej: directiva comercial o pedido de prueba) o volvé a grabarlo."
        ), "boss_voice_untranscribed"

    # 6. Conversational AI Response to boss via Gemini
    ai_reply, action = await generate_boss_ai_response(db, clean_text, conversation_history)
    return True, ai_reply, action

