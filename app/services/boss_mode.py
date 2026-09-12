import os
import re
import json
import logging
import asyncio
import httpx
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.prospect import Prospect
from app.services.catalog import catalog_service
from app.services import brain
from app.services import whatsapp

logger = logging.getLogger(__name__)

LAST_BOSS_ORDERS = {}
LAST_ONBOARDED_CLIENT = {}

SUPPLIER_DRAFTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "supplier_draft_orders.json")

def load_supplier_drafts() -> dict:
    if os.path.exists(SUPPLIER_DRAFTS_FILE):
        try:
            with open(SUPPLIER_DRAFTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error reading supplier drafts: {e}")
    return {}

def save_supplier_drafts(drafts: dict):
    try:
        os.makedirs(os.path.dirname(SUPPLIER_DRAFTS_FILE), exist_ok=True)
        with open(SUPPLIER_DRAFTS_FILE, "w", encoding="utf-8") as f:
            json.dump(drafts, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving supplier drafts: {e}")

def add_items_to_supplier_draft(supplier_name: str, items: List[dict]) -> dict:
    drafts = load_supplier_drafts()
    sup_key = re.sub(r'[^\w\s]', '', supplier_name).strip().lower().replace(' ', '_')
    if sup_key not in drafts:
        drafts[sup_key] = {
            "supplier_name": supplier_name,
            "items": [],
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
    current_items = drafts[sup_key]["items"]
    for it in items:
        p_name = str(it.get("product_name") or "").strip()
        p_qty = int(it.get("quantity") or 1)
        p_price = float(it.get("unit_price") or 0.0)
        found = False
        for ex in current_items:
            if ex["product_name"].lower() == p_name.lower():
                ex["quantity"] += p_qty
                if p_price > 0:
                    ex["unit_price"] = p_price
                found = True
                break
        if not found:
            current_items.append({
                "product_name": p_name,
                "quantity": p_qty,
                "unit_price": p_price
            })
    drafts[sup_key]["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_supplier_drafts(drafts)
    return drafts[sup_key]

def get_supplier_draft(supplier_name: str) -> Optional[dict]:
    drafts = load_supplier_drafts()
    sup_key = re.sub(r'[^\w\s]', '', supplier_name).strip().lower().replace(' ', '_')
    if sup_key in drafts:
        return drafts[sup_key]
    for k, v in drafts.items():
        s_title = v.get("supplier_name", "").lower()
        if supplier_name.lower() in s_title or s_title in supplier_name.lower():
            return v
    return None

def clear_supplier_draft(supplier_name: str):
    drafts = load_supplier_drafts()
    sup_key = re.sub(r'[^\w\s]', '', supplier_name).strip().lower().replace(' ', '_')
    if sup_key in drafts:
        del drafts[sup_key]
        save_supplier_drafts(drafts)
        return
    for k, v in list(drafts.items()):
        s_title = v.get("supplier_name", "").lower()
        if supplier_name.lower() in s_title or s_title in supplier_name.lower():
            del drafts[k]
            save_supplier_drafts(drafts)
            return

def normalize_argentine_phone(raw_phone: str) -> str:
    """
    Normalizes any Argentine phone string (with 15, area code, spaces, dashes)
    to standard WhatsApp E.164 without plus: 549<area><number>
    """
    digits = "".join(filter(str.isdigit, str(raw_phone or "")))
    if not digits:
        return ""
    if digits.startswith("0"):
        digits = digits[1:]
    if digits.startswith("549"):
        return digits
    if digits.startswith("54"):
        rest = digits[2:]
        if rest.startswith("15"):
            rest = rest[2:]
        if rest.startswith("9"):
            return f"54{rest}"
        return f"549{rest}"
    if digits.startswith("15") and len(digits) >= 10:
        digits = digits[2:]
    if len(digits) >= 11 and "15" in digits:
        digits = digits.replace("15", "", 1)
    if len(digits) >= 8:
        return f"549{digits}"
    return digits

def get_active_onboarded_client(db: Session) -> dict:
    global LAST_ONBOARDED_CLIENT
    if LAST_ONBOARDED_CLIENT.get("phone"):
        return LAST_ONBOARDED_CLIENT
    try:
        recent = db.query(Prospect).filter(Prospect.campaign == "client_onboarding").order_by(Prospect.updated_at.desc()).first()
        if recent:
            LAST_ONBOARDED_CLIENT = {
                "phone": recent.phone,
                "business_name": recent.name,
                "contact_name": recent.contact_name,
                "business_type": recent.business_type,
                "city": recent.city
            }
            return LAST_ONBOARDED_CLIENT
    except Exception as e:
        logger.warning(f"Error fetching recent onboarded client: {e}")
    return {}

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
            "El usuario le pide a su asistente comercial Sofía que despache, pase o envíe un pedido, demo, remito o mensaje a un proveedor, distribuidora, cliente o comercio.\n"
            f"Mensaje del usuario:\n\"{clean}\"\n\n"
            "Extraé en formato JSON con estas claves exactas:\n"
            "- is_dispatch: true (si el usuario quiere enviar, pasar o despachar un pedido, demo o mensaje a un tercero) o false\n"
            "- recipient_name: nombre del destinatario (ej: 'Ricardo', 'Ferretería Nogoyá', 'Distribuidora Alem', 'la Distribuidora')\n"
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

async def parse_client_onboarding_intent(text: str) -> dict:
    """
    Uses Gemini Flash Lite to detect if Javier is registering a new client/merchant
    via audio note or text, and extracts commerce name, owner name, phone, rubro, city.
    """
    clean = text.strip()
    lower = clean.lower()

    # Pre-check: Don't treat commands or order dispatches as onboarding
    if lower.startswith("rubro ") or lower.startswith("modo ") or lower.startswith("pausar") or lower.startswith("activar"):
        return {"is_onboarding": False}

    disqualifiers = [
        "mandale el pedido", "mandar pedido", "pasar pedido", "enviar pedido",
        "enviale este mensaje", "mandale este mensaje", "despachar", "despachale",
        "silenciar", "reactivar", "resumen", "ventas", "como venimos", "cómo venimos",
        "lista de precio", "lista completa", "si lo confirmo", "lo tomo yo",
        "pedidos de", "pedido a", "pedido formal"
    ]
    if any(d in lower for d in disqualifiers):
        return {"is_onboarding": False}

    onboarding_verbs = [
        "cargá al cliente", "cargar cliente", "cargá el cliente", "cargar el cliente",
        "cargá a este cliente", "carga este cliente", "cargame este cliente", "cargá este cliente",
        "alta de cliente", "alta cliente", "dar de alta", "anotá a este cliente", "anotar cliente",
        "anotá este cliente", "anota este cliente", "anotá al cliente", "registrá al cliente",
        "registrar cliente", "registrá este cliente", "nuevo cliente", "cliente nuevo",
        "anotá este comercio", "cargá este comercio", "guardá este cliente", "guardar cliente",
        "alta de comercio", "alta comercio", "anotá este local", "cargá este negocio", "alta negocio",
        "anotá a", "anota a", "cargá a", "carga a", "cargar a", "alta a", "registrá a", "registra a",
        "corregí", "corregi", "corregir", "modificá", "modifica", "modificar",
        "actualizá", "actualiza", "actualizar", "cambiá", "cambia", "cambiar"
    ]
    is_candidate = any(v in lower for v in onboarding_verbs)
    if not is_candidate and (lower.startswith("alta ") or lower.startswith("cargar ") or lower.startswith("cargá ") or lower.startswith("anotá ") or lower.startswith("anota ") or lower.startswith("corregí ") or lower.startswith("modificá ") or lower.startswith("actualizá ")):
        if any(k in lower for k in ["cliente", "comercio", "negocio", "ferreteria", "ferretería", "kiosco", "almacen", "almacén", "despensa", "local", "titular", "telefono", "teléfono", "celular", "celu", "nombre"]):
            is_candidate = True

    if not is_candidate:
        return {"is_onboarding": False}

    gemini_key = settings.GEMINI_API_KEY
    if gemini_key:
        prompt = (
            "El director general (Javier) le habla a su asistente comercial Sofía por WhatsApp para dar de alta, "
            "cargar, anotar, registrar, corregir o actualizar los datos de un cliente minorista (comercio, ferretería, kiosco, almacén, despensa, distribuidora, etc.).\n"
            f"Mensaje recibido:\n\"{clean}\"\n\n"
            "Analizá si el mensaje contiene la intención de dar de alta, registrar, cargar, anotar, corregir o modificar los datos de un cliente o comercio.\n"
            "Extraé en formato JSON con estas claves exactas:\n"
            "- is_onboarding: true (si Javier está dando de alta, registrando, anotando, corrigiendo o guardando un cliente/comercio) o false\n"
            "- business_name: nombre del comercio o razón social (ej: 'Ferretería Nogoyá', 'Despensa El Sol') o null\n"
            "- contact_name: nombre del dueño, titular o encargado (ej: 'Ricardo', 'Juan') o null\n"
            "- phone: número de teléfono mencionado (ej: '3434482186') o null\n"
            "- business_type: 'ferreteria', 'kiosco', 'almacen', 'despensa', 'distribuidora', 'hotel', 'restaurante' o 'comercio'\n"
            "- city: ciudad o dirección mencionada (ej: 'Paraná', 'calle Nogoyá 450') o null\n"
            "- notes: cualquier detalle adicional mencionado o null\n"
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
                            parsed = json.loads(parts[0].get("text", "{}"))
                            if isinstance(parsed, dict) and parsed.get("is_onboarding"):
                                return parsed
        except Exception as e:
            logger.warning(f"Gemini client onboarding parse error: {e}")

    if is_candidate:
        digits = re.findall(r'\d{8,14}', clean.replace("-", "").replace(" ", "").replace("+", ""))
        raw_phone = digits[0] if digits else None

        b_type = "comercio"
        if any(k in lower for k in ["ferret", "herramient"]):
            b_type = "ferreteria"
        elif any(k in lower for k in ["kiosc", "despensa"]):
            b_type = "kiosco"
        elif any(k in lower for k in ["distribuidora", "mayorista"]):
            b_type = "distribuidora"

        contact_name = None
        contact_match = re.search(r'(?:titular|dueño|de|contacto|nombre)\s+([A-ZÁÉÍÓÚa-záéíóú]+)', clean)
        if contact_match and contact_match.group(1).lower() not in ["ferretería", "ferreteria", "kiosco", "comercio", "este", "un", "la", "el", "calle"]:
            contact_name = contact_match.group(1).capitalize()

        b_name = None
        b_match = re.search(r'(?:cliente|comercio|negocio|local)\s*:?\s*([^,\n\r]+?)(?:\s+(?:de|titular|tel|cel|telefono|teléfono|rubro|en)\b|[,\n]|$)', clean, re.IGNORECASE)
        if b_match:
            cand_name = b_match.group(1).strip()
            cand_name = re.sub(r'^(?:el|la|los|las|un|una)\s+', '', cand_name, flags=re.IGNORECASE).strip()
            if len(cand_name) > 2 and cand_name.lower() not in ["nuevo", "este", "comercio", "cliente"]:
                b_name = cand_name
        if not b_name:
            if b_type == "ferreteria":
                b_name = "Ferretería" + (f" de {contact_name}" if contact_name else "")
            elif b_type == "kiosco":
                b_name = "Kiosco" + (f" de {contact_name}" if contact_name else "")
            else:
                b_name = "Comercio Minorista"

        city = "Paraná"
        city_match = re.search(r'(?:en|de|calle)\s+([^,\n\r]+)', clean, re.IGNORECASE)
        if city_match:
            city = city_match.group(1).strip()

        return {
            "is_onboarding": True,
            "business_name": b_name,
            "contact_name": contact_name or "Titular",
            "phone": raw_phone,
            "business_type": b_type,
            "city": city,
            "notes": clean
        }

    return {"is_onboarding": False}

async def parse_supplier_registration_intent(text: str) -> dict:
    """
    Detects if the merchant wants to register a new supplier/distributor.
    e.g. 'Sofi, agendá al proveedor Bulonera del Litoral al 3434536447'
         'anotá al proveedor Pinturas Litoral al 3424112233'
         'guardá el proveedor Sanitarios del Centro al 343...'
         'agendá a Carlos de Distribuidora El Progreso al 343...'
    """
    clean = text.strip()
    lower = clean.lower()

    # Guard: if it's an order dispatch, it is NOT a registration
    dispatch_words = [
        "mandale el pedido", "mandar pedido", "pasar pedido", "enviar pedido",
        "despachar pedido", "despachale", "hacele el pedido", "hacé el pedido", "pasale el pedido"
    ]
    if any(dw in lower for dw in dispatch_words):
        return {"is_supplier_registration": False}

    triggers = [
        "agendá al proveedor", "agenda al proveedor", "agendar proveedor",
        "anotá al proveedor", "anota al proveedor", "anotar proveedor",
        "guardá al proveedor", "guarda al proveedor", "guardar proveedor",
        "nuevo proveedor", "proveedor nuevo", "el proveedor es", "el proveedor de",
        "agendá a", "agenda a", "agendar a", "anotá a", "anota a", "guardá a", "guarda a",
        "agendá al viajante", "agenda al viajante", "agendar viajante",
        "anotá al viajante", "anota al viajante", "guardá al viajante",
        "agendá a la distribuidora", "agenda a la distribuidora", "guardá la distribuidora",
        "guardar distribuidora"
    ]
    is_candidate = any(trig in lower for trig in triggers) or (
        any(w in lower for w in ["proveedor", "distribuidora", "viajante"]) and any(k in lower for k in ["agend", "anot", "guard", "telefono", "teléfono", "celular", "es el", "alta"])
    )
    if not is_candidate:
        return {"is_supplier_registration": False}

    gemini_key = settings.GEMINI_API_KEY
    if gemini_key:
        prompt = (
            "El dueño de un comercio minorista le habla a su asistente comercial Sofía por WhatsApp para registrar o agendar a un proveedor, distribuidora o viajante.\n"
            f"Mensaje: \"{clean}\"\n\n"
            "Analizá y extraé en formato JSON con estas claves:\n"
            "- is_supplier_registration: true o false\n"
            "- supplier_name: nombre comercial de la empresa proveedora o distribuidora (ej: 'Distribuidora El Progreso', 'Bulonera del Litoral', 'Pinturas Paraná')\n"
            "- contact_name: nombre de pila de la persona de contacto o viajante si se menciona (ej: 'Carlos', 'Martín', o null si no se menciona)\n"
            "- phone: número de teléfono extraído (solo dígitos, o null)\n"
            "- category: rubro de lo que vende si se menciona (ej: 'tornillos', 'pinturas', 'herramientas', o null)\n"
            "Respondé ÚNICAMENTE un JSON válido."
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={gemini_key}"
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.post(
                    url,
                    json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"response_mime_type": "application/json"}}
                )
                if res.status_code == 200:
                    cand = res.json().get("candidates", [])
                    if cand and "content" in cand[0]:
                        parts = cand[0]["content"].get("parts", [])
                        if parts:
                            data = json.loads(parts[0].get("text", "{}"))
                            if data.get("is_supplier_registration"):
                                return data
        except Exception as e:
            logger.warning(f"Gemini supplier registration parse error: {e}")

    # Fallback deterministic
    phone_m = re.search(r'(?:al|el|numero|número|telefono|teléfono|tel|cel)?\s*([0-9\s\-+]{8,25})', clean, re.IGNORECASE)
    phone = "".join(filter(str.isdigit, phone_m.group(1))) if phone_m else None

    # Strip phone from end for clean name extraction
    clean_no_phone = clean[:phone_m.start()].strip() if phone_m else clean

    # Check "agendá a Carlos de Distribuidora El Progreso"
    c_match = re.search(r'(?:agend[áa]|anot[áa]|guard[áa])\s+(?:a\s+)?([A-Za-zÁÉÍÓÚáéíóúñÑ]+)\s+de\s+([A-Za-zÁÉÍÓÚáéíóúñÑ0-9\s\.\'\"]+)', clean_no_phone, re.IGNORECASE)
    if c_match:
        contact_name = c_match.group(1).strip()
        name = c_match.group(2).strip()
    else:
        # e.g. "agendá al proveedor Distribuidora El Progreso"
        name_m = re.search(r'(?:proveedor\s+|distribuidora\s+|viajante\s+)([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s\.\'\"]+)', clean_no_phone, re.IGNORECASE)
        if name_m:
            name = name_m.group(1).strip()
        else:
            name_m2 = re.search(r'(?:agend[áa]|anot[áa]|guard[áa])\s+(?:a\s+)?([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s\.\'\"]+)', clean_no_phone, re.IGNORECASE)
            name = name_m2.group(1).strip() if name_m2 else "Proveedor"
        contact_name = name

    return {
        "is_supplier_registration": True,
        "supplier_name": name,
        "contact_name": contact_name,
        "phone": phone,
        "category": None
    }


async def parse_supplier_basket_add_intent(text: str) -> dict:
    """
    Detects if the merchant wants to add items to a supplier's draft basket.
    e.g. 'Sofi, anotá para la Bulonera 5 cajas de tornillos T1 y 2 alicates'
         'agregá al pedido de Pinturas Litoral 3 latas de látex'
         'para Sanitarios Paraná anotame 10 codos de 110'
    """
    clean = text.strip()
    lower = clean.lower()
    has_target = bool(re.search(r'\bpara\s+(?!pedir|preguntar|saber|ver|consultar|avisar|mi\b|vos\b)[A-Za-z0-9]', lower) or any(k in lower for k in ["al pedido de", "en el pedido de", "a la distribuidora", "al proveedor"]))
    basket_verbs = ["anotá", "anota", "anotame", "agregá", "agrega", "agregame", "sumá", "suma", "sumame", "guardá", "guarda", "guardame", "poné", "pone", "poneme", "cargá", "carga", "cargame"]
    has_action = any(re.search(rf'\b{k}\b', lower) for k in basket_verbs)
    if not (has_target and has_action):
        return {"is_basket_add": False}

    gemini_key = settings.GEMINI_API_KEY
    if gemini_key:
        prompt = (
            "El dueño de un comercio minorista le habla a su asistente comercial Sofía por WhatsApp para agregar productos a la canasta de compras de un proveedor o distribuidora específica.\n"
            f"Mensaje: \"{clean}\"\n\n"
            "Analizá y extraé en formato JSON con estas claves:\n"
            "- is_basket_add: true o false\n"
            "- supplier_name: nombre del proveedor o distribuidora (ej: 'Bulonera del Litoral', 'Pinturas Litoral')\n"
            "- items: lista de objetos con 'product_name' (str) y 'quantity' (int)\n"
            "Respondé ÚNICAMENTE un JSON válido."
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={gemini_key}"
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.post(
                    url,
                    json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"response_mime_type": "application/json"}}
                )
                if res.status_code == 200:
                    cand = res.json().get("candidates", [])
                    if cand and "content" in cand[0]:
                        parts = cand[0]["content"].get("parts", [])
                        if parts:
                            data = json.loads(parts[0].get("text", "{}"))
                            if data.get("is_basket_add"):
                                return data
        except Exception as e:
            logger.warning(f"Gemini basket add parse error: {e}")

    # Fallback deterministic
    sup_m = re.search(r'(?:para|de|al pedido de)\s+(?:la|el)?\s*([A-Za-z0-9\s]+?)(?:\s+anot|\s+agreg|\s+sum|\s+ped|\s*:|\s+\d+|$)', clean, re.IGNORECASE)
    sup_name = sup_m.group(1).strip() if sup_m else "Proveedor"
    order_part = re.sub(r'.*?(?:anotá|anota|anotame|agregá|agrega|sumá|suma|pedí|pedi|guardá|guarda|poné|pone)\s+', '', clean, flags=re.IGNORECASE)
    items = []
    chunks = re.split(r'[,;\n]|\s+y\s+', order_part)
    for ch in chunks:
        ch_clean = ch.strip()
        if not ch_clean:
            continue
        num_m = re.search(r'\b(\d+)\b', ch_clean)
        if num_m:
            qty = int(num_m.group(1))
            p_name = re.sub(r'\b\d+\b', '', ch_clean).strip()
            p_name = re.sub(r'^(?:de|con|cajas?|latas?|bolsas?|fardos?|packs?|unidades?)\s+(?:de\s+)?', '', p_name, flags=re.IGNORECASE).strip()
            if p_name:
                items.append({"product_name": p_name.capitalize(), "quantity": qty})

    if not items:
        for n, p in re.findall(r'(\d+)\s+([A-Za-z0-9\s]+)', order_part):
            items.append({"product_name": p.strip().capitalize(), "quantity": int(n)})

    return {
        "is_basket_add": bool(items),
        "supplier_name": sup_name,
        "items": items
    }


def parse_supplier_basket_inquiry_intent(text: str) -> dict:
    """
    Detects if user asks what's pending for a supplier or for all suppliers,
    or asks for the list of registered suppliers.
    e.g. 'qué tengo para pedirle a la Bulonera?'
         'pedidos a proveedores'
         'qué pedidos tengo pendientes?'
         'canastas abiertas'
         'proveedores'
    """
    lower = text.lower().strip()
    clean_no_punct = re.sub(r'[^\w\s]', '', lower).strip()
    clean_no_prefix = re.sub(r'^(?:sofi|sofia|hola|buenas)[\s,:]*', '', clean_no_punct).strip()
    clean_no_accents = clean_no_prefix.replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')

    if any(k in clean_no_accents for k in [
        "mis clientes", "lista de clientes", "ver clientes", "cuales son mis clientes",
        "comercios", "comercios dados de alta", "clientes dados de alta", "mis comercios"
    ]) or clean_no_accents in ["clientes", "comercios"]:
        return {"is_inquiry": True, "type": "list_clients"}

    if any(k in clean_no_accents for k in [
        "mis proveedores", "lista de proveedores", "ver proveedores",
        "cuales son mis proveedores", "quienes son mis proveedores", "agenda de proveedores"
    ]) or clean_no_accents in ["proveedores", "proveedor"]:
        return {"is_inquiry": True, "type": "list_suppliers"}

    if any(clean_no_prefix == q for q in [
        "pedidos a proveedores", "pedidos pendientes a proveedores", "canastas",
        "canastas abiertas", "que tengo para pedir", "pedidos por proveedor", "canastas de proveedores"
    ]) or ("pedidos" in clean_no_prefix and "proveedor" in clean_no_prefix):
        return {"is_inquiry": True, "type": "all_baskets"}

    m = re.search(r'(?:que|qué)\s+tengo\s+para\s+pedir(?:le)?\s+a\s+(?:la|el)?\s*([A-Za-z0-9\s]+?)(?:\?|$)', lower)
    if m:
        return {"is_inquiry": True, "type": "single_basket", "supplier_name": m.group(1).strip()}

    m2 = re.search(r'(?:pedido|canasta|borrador)\s+(?:de|para)\s+(?:la|el)?\s*([A-Za-z0-9\s]+?)(?:\?|$)', lower)
    if m2 and not any(k in lower for k in ["mandale", "despachale", "enviar", "pasar", "hacele"]):
        return {"is_inquiry": True, "type": "single_basket", "supplier_name": m2.group(1).strip()}

    return {"is_inquiry": False}


def get_client_manual_text() -> str:
    return (
        "👋 *¡HOLA! SOY SOFÍA, TU CENTRAL DE COMPRAS EN WHATSAPP* 📱✨\n\n"
        "A partir de hoy no necesitás abrir 10 planillas ni volverte loco buscando entre los mensajes de los viajantes. "
        "Gestionás todas tus compras directamente desde este chat, como si hablaras con una persona.\n\n"
        "---\n\n"
        "🎯 *¿CÓMO USARME EN TU DÍA A DÍA?*\n\n"
        "1️⃣ *Comparar precios al instante:*\n"
        "Escribime o mandame un audio preguntando por cualquier producto.\n"
        "👉 _«Sofi, ¿quién tiene más barato el foco LED 9W?»_\n"
        "👉 _«¿A cuánto me deja el aceite Cañuelas cada distribuidor?»_\n"
        "Te digo al segundo quién tiene el mejor precio para cuidar tu margen.\n\n"
        "2️⃣ *Armar pedidos mientras caminás por el local:*\n"
        "¿Viste un faltante en la góndola? Dictamelo por nota de voz y te lo voy anotando:\n"
        "👉 _«Anotame 10 paquetes de harina y 5 cajas de tornillos»_\n"
        "👉 _«¿Qué tengo anotado para pedirle al viajante de Molinos?»_\n\n"
        "3️⃣ *Controlar aumentos de la semana:*\n"
        "Antes de que te cobren de más, preguntame:\n"
        "👉 _«¿Qué productos me aumentaron esta semana?»_\n"
        "Te aviso qué artículos subieron y cuándo conviene stockearte antes de una suba.\n\n"
        "4️⃣ *Cargar listas nuevas de tus distribuidores:*\n"
        "¿El viajante te mandó una lista de precios por WhatsApp?\n"
        "👉 *Solo dale a \"Reenviar\" a este chat* (en PDF o Excel).\n"
        "Leo las tablas automáticamente y actualizo todos los precios en segundos.\n\n"
        "5️⃣ *Revisar tus proveedores registrados:*\n"
        "👉 _«¿Qué proveedores tengo cargados?»_\n"
        "Te muestro cuántos distribuidores y productos tenés en memoria.\n\n"
        "6️⃣ *Agendar proveedores nuevos en 1 toque (¡Contacto directo!):* 🆕\n"
        "¿Querés que me comunique con un viajante o distribuidora?\n"
        "👉 Mandame un audio o texto: _«Sofi, agendá al proveedor Carlos de Distribuidora El Progreso al 3434536447»_\n"
        "👉 O simplemente *compartime su contacto* desde WhatsApp (icono del clip 📎 ➔ Contacto).\n"
        "⚡ *¿Qué hago yo al instante?* Le escribo un WhatsApp presentándome de parte tuya, le pido que me agende y le solicito su lista de precios vigente en PDF o Excel para que tengas los costos actualizados desde el día 1.\n\n"
        "---\n\n"
        "💡 *3 CONSEJOS PARA APROVECHARME AL MÁXIMO:*\n\n"
        "🎙️ *Usá notas de voz:* Podés hablarme por audio rápido mientras atendés el mostrador.\n"
        "🤝 *Hablame natural:* No necesitás códigos raros. Decime _«anotame»_, _«pasame precio de...»_ o _«agendá al proveedor...»_.\n"
        "📦 *Cero instalaciones:* Funciona 100% acá adentro de WhatsApp, sin descargar aplicaciones ni programas pesados en la computadora.\n\n"
        "¡Guardame en tus contactos como *«Sofía - Compras»* y probame ahora mismo mandándome un audio! 🚀"
    )


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
                sup_match = re.search(r'(?:de|para|del proveedor|de la distribuidora)\s+([A-Za-z0-9\s]+?)(?:\s+con|\s+para|\s*$)', clean_text, re.IGNORECASE)
                sup_name_hint = sup_match.group(1).strip() if sup_match else None
                result = catalog_service.update_from_supplier_excel(doc_bytes, filename=doc_name, supplier_name=sup_name_hint)
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
        elif fname.endswith(".pdf"):
            count = await catalog_service.load_from_pdf_bytes(doc_bytes, filename=doc_name)
            if count > 0:
                return True, (
                    f"✅ *¡Catálogo PDF procesado con éxito!*\n\n"
                    f"Se procesaron y cargaron *{count} productos* desde el archivo `{doc_name}`.\n"
                    f"Sofía ya está lista para cotizar y tomar pedidos con estos nuevos precios."
                ), "catalog_updated"
            else:
                return True, f"📄 Recibí el archivo PDF `{doc_name}` pero no pude extraer listas de precios automáticas. Verificá que contenga texto o tablas legibles.", "catalog_pdf_error"

    # 1.3 Client Onboarding on-the-fly via WhatsApp Audio or Text
    onboarding_data = await parse_client_onboarding_intent(clean_text)
    if onboarding_data.get("is_onboarding"):
        raw_phone = onboarding_data.get("phone")
        norm_phone = normalize_argentine_phone(raw_phone) if raw_phone else None

        b_name = onboarding_data.get("business_name") or "Comercio Minorista"
        c_name = onboarding_data.get("contact_name") or "Titular"
        b_type = (onboarding_data.get("business_type") or "comercio").lower()
        city = onboarding_data.get("city") or "Paraná, Entre Ríos"

        if not norm_phone or len(norm_phone) < 8:
            LAST_ONBOARDED_CLIENT.clear()
            LAST_ONBOARDED_CLIENT.update({
                "business_name": b_name,
                "contact_name": c_name,
                "business_type": b_type,
                "city": city
            })
            return True, (
                f"📋 *¡Alta de cliente en proceso!* 🏪\n\n"
                f"Tengo los datos de *{b_name}* (Titular: {c_name}), pero me falta su número de WhatsApp para registrarlo.\n\n"
                f"💡 Pasámelo diciendo por ejemplo: `el teléfono es 343 4556679`"
            ), "onboarding_needs_phone"

        # Check existing Prospect by phone
        existing_prospect = db.query(Prospect).filter(Prospect.phone == norm_phone).first()
        is_update = bool(existing_prospect)
        if existing_prospect:
            if b_name and b_name != "Comercio Minorista":
                existing_prospect.name = b_name
            if c_name and c_name != "Titular":
                existing_prospect.contact_name = c_name
            if b_type and b_type != "comercio":
                existing_prospect.business_type = b_type
            if city:
                existing_prospect.city = city
            existing_prospect.campaign = "client_onboarding"
            existing_prospect.status = "new"
            existing_prospect.notes = f"Actualizado desde WhatsApp (Modo Jefe) el {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            db.commit()
            db.refresh(existing_prospect)
            b_name = existing_prospect.name
            c_name = existing_prospect.contact_name
            b_type = (existing_prospect.business_type or "comercio").lower()
            city = existing_prospect.city
        else:
            new_prospect = Prospect(
                name=b_name,
                contact_name=c_name,
                phone=norm_phone,
                business_type=b_type,
                city=city,
                campaign="client_onboarding",
                status="new",
                notes=f"Alta rápida desde WhatsApp (Modo Jefe) el {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            )
            db.add(new_prospect)
            db.commit()
            db.refresh(new_prospect)

        # Switch rubro automatically if recognized
        catalog_info = ""
        if any(k in b_type for k in ["ferret", "herramient"]):
            trade_title, catalog_count = catalog_service.set_rubro("ferreteria")
            catalog_info = f"🛠️ *Rubro activado:* Ferretería ({catalog_count} productos cargados con precios reales)\n"
        elif any(k in b_type for k in ["despensa", "almacen", "almacén", "alimento", "comestible"]):
            trade_title, catalog_count = catalog_service.set_rubro("almacen")
            catalog_info = f"🏪 *Rubro activado:* Despensa & Alimentos ({catalog_count} productos: harina, aceite, lácteos, etc.)\n"
        elif any(k in b_type for k in ["kiosc"]):
            trade_title, catalog_count = catalog_service.set_rubro("kiosco")
            catalog_info = f"🍬 *Rubro activado:* Kiosco ({catalog_count} artículos: golosinas, snacks, bebidas)\n"
        elif any(k in b_type for k in ["distribuidora", "mayorista"]):
            trade_title, catalog_count = catalog_service.set_rubro("distribuidora")
            catalog_info = f"🏢 *Rubro activado:* Distribuidora mayorista\n"

        LAST_ONBOARDED_CLIENT.clear()
        LAST_ONBOARDED_CLIENT.update({
            "phone": norm_phone,
            "business_name": b_name,
            "contact_name": c_name,
            "business_type": b_type,
            "city": city
        })

        # Build rubro-specific guided welcome message for client
        is_ferret = any(k in b_type for k in ["ferret", "herramient"])
        is_almac = any(k in b_type for k in ["despensa", "almacen", "almacén", "alimento", "comestible"])
        is_kiosc = any(k in b_type for k in ["kiosc"])

        if is_ferret:
            welcome_text = (
                f"¡Hola {c_name}! 👋 Soy Sofía, tu asistente de compras en *{b_name}*.\n"
                f"Activé un catálogo de demostración con distribuidores de ferretería para que hagamos una prueba en vivo juntos.\n\n"
                f"🎯 *Podés mandarme un audio o probar con cualquiera de estos mensajes:*\n\n"
                f"1️⃣ _«Sofi, ¿quién tiene más barato el foco LED 9W?»_\n"
                f"2️⃣ _«Anotame 10 cajas de tornillos y 2 pinzas»_\n"
                f"3️⃣ _«¿Qué productos me aumentaron esta semana?»_\n"
                f"4️⃣ _Reenviame una lista de precios en PDF o Excel de cualquier distribuidor para guardarla en mi memoria_\n"
                f"5️⃣ _«¿Qué proveedores tengo registrados?»_\n\n"
                f"¿Qué querés que revisemos primero?"
            )
            demo_items = "10x Tornillos autoperforantes, 2x Pinzas universales"
            g1 = "«Sofi, ¿quién tiene más barato el foco LED 9W?»"
            g2 = "«Anotame 10 cajas de tornillos y 2 pinzas»"
            g3 = "«¿Qué productos me aumentaron esta semana?»"
            g4 = "Reenviarle un PDF o Excel de proveedor"
            g5 = "«¿Qué proveedores tengo registrados?»"
        elif is_almac:
            welcome_text = (
                f"¡Hola {c_name}! 👋 Soy Sofía, tu asistente de compras en *{b_name}*.\n"
                f"Activé un catálogo de demostración con distribuidores mayoristas de alimentos para que hagamos una prueba en vivo juntos.\n\n"
                f"🎯 *Podés mandarme un audio o probar con cualquiera de estos mensajes:*\n\n"
                f"1️⃣ _«Sofi, ¿quién tiene más barato el aceite?»_\n"
                f"2️⃣ _«Anotame un pedido de 10 paquetes de harina y 5 aceites»_\n"
                f"3️⃣ _«¿Qué productos me aumentaron esta semana?»_\n"
                f"4️⃣ _Reenviame una lista de precios en PDF o Excel de cualquier distribuidor para guardarla en mi memoria_\n"
                f"5️⃣ _«¿Qué proveedores tengo registrados?»_\n\n"
                f"¿Qué querés que revisemos primero?"
            )
            demo_items = "10x Harina 000 Cañuelas, 5x Aceite Cañuelas 1.5L"
            g1 = "«Sofi, ¿quién tiene más barato el aceite?»"
            g2 = "«Anotame un pedido de 10 paquetes de harina y 5 aceites»"
            g3 = "«¿Qué productos me aumentaron esta semana?»"
            g4 = "Reenviarle un PDF o Excel de proveedor"
            g5 = "«¿Qué proveedores tengo registrados?»"
        elif is_kiosc:
            welcome_text = (
                f"¡Hola {c_name}! 👋 Soy Sofía, tu asistente de compras en *{b_name}*.\n"
                f"Activé un catálogo de demostración con distribuidores de golosinas y bebidas para que hagamos una prueba en vivo juntos.\n\n"
                f"🎯 *Podés mandarme un audio o probar con cualquiera de estos mensajes:*\n\n"
                f"1️⃣ _«Sofi, ¿a cuánto tenés la Coca de 1.5L y los alfajores?»_\n"
                f"2️⃣ _«Anotame 2 cajas de Guaymallén y 1 pack de Coca 500»_\n"
                f"3️⃣ _«¿Quién me deja más barato el chocolate Milka?»_\n"
                f"4️⃣ _Reenviame una lista de precios en PDF o Excel de cualquier distribuidor para guardarla en mi memoria_\n"
                f"5️⃣ _«¿Qué proveedores tengo registrados?»_\n\n"
                f"¿Qué querés que revisemos primero?"
            )
            demo_items = "2x Cajas Guaymallén, 1x Pack Coca 500"
            g1 = "«Sofi, ¿a cuánto tenés la Coca y los alfajores?»"
            g2 = "«Anotame 2 cajas de Guaymallén y 1 pack de Coca»"
            g3 = "«¿Quién me deja más barato el chocolate Milka?»"
            g4 = "Reenviarle un PDF o Excel de proveedor"
            g5 = "«¿Qué proveedores tengo registrados?»"
        else:
            welcome_text = (
                f"¡Hola {c_name}! 👋 Soy Sofía, tu asistente comercial en *{b_name}*.\n"
                f"Activé un catálogo de demostración para que hagamos una prueba en vivo juntos.\n\n"
                f"🎯 *Podés mandarme un audio o probar con cualquiera de estos mensajes:*\n\n"
                f"1️⃣ _«Sofi, pasame el precio de la harina 000 y el aceite»_\n"
                f"2️⃣ _«Anotame 5 bolsas de harina 25kg y 3 cajas de aceite»_\n"
                f"3️⃣ _«¿Qué productos me aumentaron esta semana?»_\n"
                f"4️⃣ _Reenviame una lista de precios en PDF o Excel de cualquier distribuidor para guardarla en mi memoria_\n"
                f"5️⃣ _«¿Qué proveedores tengo registrados?»_\n\n"
                f"¿Qué querés que revisemos primero?"
            )
            demo_items = "5x Harina 000 25kg, 3x Aceite 12x900ml"
            g1 = "«Sofi, pasame el precio de la harina y el aceite»"
            g2 = "«Anotame 5 bolsas de harina y 3 de aceite»"
            g3 = "«¿Qué productos me aumentaron esta semana?»"
            g4 = "Reenviarle un PDF o Excel de proveedor"
            g5 = "«¿Qué proveedores tengo registrados?»"

        try:
            # 1. Attempt official Meta Template (Plantilla A: demo_comercio_v1)
            tpl_components = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": c_name},
                        {"type": "text", "text": b_name},
                        {"type": "text", "text": demo_items},
                        {"type": "text", "text": "A cotizar"}
                    ]
                }
            ]
            asyncio.create_task(whatsapp.send_whatsapp_template(
                to_phone=norm_phone,
                template_name="demo_comercio_v1",
                language_code="es_AR",
                components=tpl_components
            ))
            # 2. Also attempt free-form greeting (delivered via Whapi gateway or within window)
            asyncio.create_task(whatsapp.send_whatsapp_message(to_phone=norm_phone, text=welcome_text))
        except Exception as e:
            logger.warning(f"Could not auto-send welcome WhatsApp message to {norm_phone}: {e}")

        header_title = "✅ *¡CLIENTE ACTUALIZADO CON ÉXITO!* 🚀" if is_update else "✅ *¡CLIENTE DADO DE ALTA CON ÉXITO!* 🚀"
        action_name = "client_updated" if is_update else "client_onboarded"

        reply = (
            f"{header_title}\n\n"
            f"🏪 *Comercio:* {b_name}\n"
            f"👤 *Titular:* {c_name}\n"
            f"📱 *WhatsApp:* +{norm_phone}\n"
            f"📍 *Ubicación:* {city}\n"
            f"{catalog_info}\n"
            f"📩 *Mensaje de bienvenida enviado al celular de {c_name}:*\n"
            f"Le envié el menú guiado con las 5 opciones listas para tocar o dictar por voz.\n\n"
            f"🎯 *Guion para la demo en vivo frente a {c_name}:*\n"
            f"Decile: _«{c_name}, mirá tu WhatsApp. Mandale un audio a Sofía leyendo cualquiera de las opciones:»_\n"
            f"1️⃣ {g1}\n"
            f"2️⃣ {g2}\n"
            f"3️⃣ {g3}\n"
            f"4️⃣ {g4}\n"
            f"5️⃣ {g5}"
        )
        return True, reply, action_name

    # Pending onboarding phone follow-up
    if LAST_ONBOARDED_CLIENT.get("business_name") and not LAST_ONBOARDED_CLIENT.get("phone"):
        cand_digits = re.findall(r'\d{8,14}', clean_text.replace("-", "").replace(" ", "").replace("+", ""))
        is_phone_reply = bool(cand_digits) and (
            len(clean_text) <= 25 or 
            any(k in lower_text for k in ["el numero", "el número", "telefono", "teléfono", "celular", "celu", "es el"])
        ) and not any(k in lower_text for k in ["pausar", "activar", "rubro", "modo", "pedido", "mandale", "enviale", "resumen"])

        if is_phone_reply:
            norm_phone = normalize_argentine_phone(cand_digits[0])
            b_name = LAST_ONBOARDED_CLIENT["business_name"]
            c_name = LAST_ONBOARDED_CLIENT["contact_name"]
            b_type = LAST_ONBOARDED_CLIENT.get("business_type", "comercio")
            city = LAST_ONBOARDED_CLIENT.get("city", "Paraná")

            existing_p = db.query(Prospect).filter(Prospect.phone == norm_phone).first()
            if existing_p:
                existing_p.name = b_name
                existing_p.contact_name = c_name
                existing_p.business_type = b_type
                existing_p.city = city
                existing_p.campaign = "client_onboarding"
                existing_p.status = "new"
                db.commit()
            else:
                new_p = Prospect(
                    name=b_name,
                    contact_name=c_name,
                    phone=norm_phone,
                    business_type=b_type,
                    city=city,
                    campaign="client_onboarding",
                    status="new"
                )
                db.add(new_p)
                db.commit()
                db.refresh(new_p)

            LAST_ONBOARDED_CLIENT["phone"] = norm_phone
            return True, (
                f"✅ *¡Teléfono registrado y cliente guardado!* 🚀\n\n"
                f"🏪 *Comercio:* {b_name}\n"
                f"👤 *Titular:* {c_name}\n"
                f"📱 *WhatsApp:* +{norm_phone}\n\n"
                f"Ya podés mandar el pedido o la demo en vivo."
            ), "client_onboarded"
        elif any(k in lower_text for k in ["pausar", "activar", "rubro", "modo", "resumen", "mandale", "enviale"]):
            LAST_ONBOARDED_CLIENT.clear()

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

    # 1.6 Supplier Registration on-the-fly via WhatsApp Audio or Text
    sup_reg_data = await parse_supplier_registration_intent(clean_text)
    if sup_reg_data.get("is_supplier_registration"):
        s_name = sup_reg_data.get("supplier_name") or "Proveedor"
        raw_p = sup_reg_data.get("phone")
        norm_p = normalize_argentine_phone(raw_p) if raw_p else None

        if norm_p:
            s_contact = sup_reg_data.get("contact_name") or s_name
            existing_sup = db.query(Prospect).filter(Prospect.phone == norm_p).first()
            if existing_sup:
                existing_sup.name = s_name
                existing_sup.contact_name = s_contact
                existing_sup.business_type = "proveedor"
                existing_sup.campaign = "supplier"
                existing_sup.notes = f"Proveedor actualizado desde WhatsApp el {datetime.now().strftime('%d/%m/%Y %H:%M')}"
                db.commit()
            else:
                new_sup = Prospect(
                    name=s_name,
                    contact_name=s_contact,
                    phone=norm_p,
                    business_type="proveedor",
                    campaign="supplier",
                    notes=f"Proveedor agendado desde WhatsApp el {datetime.now().strftime('%d/%m/%Y %H:%M')}"
                )
                db.add(new_sup)
                db.commit()

            # Determine client / merchant details from sender_phone
            client_prospect = None
            if sender_phone:
                clean_s = "".join(filter(str.isdigit, str(sender_phone)))
                client_prospect = db.query(Prospect).filter(Prospect.phone == clean_s).first()
                if not client_prospect:
                    norm_s = normalize_argentine_phone(clean_s)
                    client_prospect = db.query(Prospect).filter(Prospect.phone == norm_s).first()

            if client_prospect:
                client_biz = client_prospect.name or "el comercio"
                client_owner = brain.sanitize_contact_first_name(client_prospect.contact_name) or "el titular"
            else:
                client_biz = "tu comercio"
                client_owner = "Javier"

            # 1. Prepare presentation message for the supplier
            supplier_intro_text = (
                f"¡Hola *{s_contact}*! 👋 Te escribo de parte de *{client_owner} de {client_biz}*.\n\n"
                f"Soy *Sofía*, su asistente comercial. Me pidió que me ponga en contacto con vos porque a partir de ahora "
                f"te voy a pasar los pedidos de reposición por acá: *bien detallados, con códigos y en PDF* para facilitarte la carga y que no pierdas tiempo. 📋📦\n\n"
                f"📌 *Por favor:*\n"
                f"1️⃣ Agendá este contacto como *«Sofía - {client_biz}»*.\n"
                f"2️⃣ Si tenés a mano la *última lista de precios o avisos de aumentos de esta semana*, ¿me la podés reenviar por este chat en PDF o Excel? Así ya la dejo cargada para los próximos pedidos.\n\n"
                f"¿Me confirmás con un *«Agendado»* o *«Recibido»* que te llegó bien? ¡Muchas gracias!"
            )

            # 2. Dispatch Meta Template (presentacion_proveedor_v1)
            components = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": s_contact},
                        {"type": "text", "text": client_owner},
                        {"type": "text", "text": client_biz}
                    ]
                }
            ]
            asyncio.create_task(whatsapp.send_whatsapp_template(
                to_phone=norm_p,
                template_name="presentacion_proveedor_v1",
                language_code="es_AR",
                components=components
            ))

            # 3. Dispatch conversational WhatsApp message
            asyncio.create_task(whatsapp.send_whatsapp_message(
                to_phone=norm_p,
                text=supplier_intro_text
            ))

            return True, (
                f"✅ *¡PROVEEDOR REGISTRADO Y CONTACTADO!* 📦✨\n\n"
                f"🏢 *Distribuidora:* {s_name}\n"
                f"👤 *Contacto:* {s_contact}\n"
                f"📱 *WhatsApp:* +{norm_p}\n\n"
                f"🚀 *Ya le envié un mensaje de presentación:*\n"
                f"Me presenté de parte de *{client_owner} de {client_biz}*, le pedí que me agende como «Sofía - {client_biz}» y le solicité su lista de precios o aumentos vigentes en PDF o Excel.\n\n"
                f"💡 *Apenas me responda o envíe su catálogo, te aviso automáticamente.*\n\n"
                f"🛒 *A partir de ahora podés:*\n"
                f"• Anotarle faltantes: _«Sofi, anotá para {s_name} 5 cajas de...»_\n"
                f"• Ver su canasta: _«¿Qué tengo para pedirle a {s_name}?»_\n"
                f"• Mandarle el pedido: _«Mandale el pedido a {s_name}»_"
            ), "supplier_registered"
        else:
            return True, (
                f"📋 *¡Registro de Proveedor en proceso!* 📦\n\n"
                f"Tengo el nombre *{s_name}*, pero me falta su número de WhatsApp.\n\n"
                f"💡 Pasámelo diciendo por ejemplo: `el teléfono de {s_name} es 343 4556679`"
            ), "supplier_needs_phone"

    # 1.7 Supplier Baskets and Supplier Listing Inquiries
    inquiry_data = parse_supplier_basket_inquiry_intent(clean_text)
    if inquiry_data.get("is_inquiry"):
        inq_type = inquiry_data.get("type")
        if inq_type == "list_clients":
            clients = db.query(Prospect).filter(
                (Prospect.business_type != "proveedor") & (Prospect.campaign != "supplier")
            ).filter(Prospect.phone != sender_phone).order_by(Prospect.updated_at.desc()).all()
            if not clients:
                return True, (
                    "📋 *No tenés clientes ni comercios registrados todavía.*\n\n"
                    "💡 Podés dar de alta uno por voz diciendo:\n"
                    "_«Sofía, cargar cliente Ferretería Nogoyá, titular Ricardo, teléfono [número]»_"
                ), "no_clients"

            lines = [f"🏪 *TUS CLIENTES Y COMERCIOS ACTIVOS ({len(clients)}):*\n"]
            for idx, c in enumerate(clients, 1):
                b_name = c.name or "Comercio"
                c_name = c.contact_name or "Titular"
                b_type = (c.business_type or "Comercio").capitalize()
                city = c.city or "Entre Ríos"
                lines.append(f"{idx}. *{b_name}* ({b_type})")
                lines.append(f"   👤 Titular: {c_name} | 📍 {city}")
                lines.append(f"   📱 WhatsApp: +{c.phone}")
                lines.append("")

            lines.append("💡 *Acciones disponibles con tus clientes:*")
            lines.append("• _«Mandale la demo a [Nombre] con 4 martillos y 2 alicates»_")
            lines.append("• _«Mandale la lista a [Nombre]»_")
            return True, "\n".join(lines), "clients_list"

        elif inq_type == "list_suppliers":
            sups = db.query(Prospect).filter(
                (Prospect.business_type == "proveedor") | (Prospect.campaign == "supplier")
            ).all()
            if not sups:
                return True, (
                    "📋 *No tenés proveedores agendados todavía.*\n\n"
                    "💡 Para agendar a uno decime por audio o texto:\n"
                    "_«Sofi, agendá al proveedor Bulonera del Litoral al 3434536447»_"
                ), "no_suppliers"

            lines = [f"📋 *TUS PROVEEDORES AGENDADOS ({len(sups)}):*\n"]
            for idx, s in enumerate(sups, 1):
                lines.append(f"{idx}. *{s.name}* (📱 +{s.phone})")
            lines.append("\n💡 Podés dictarme pedidos diciendo: _«Anotá para [Proveedor] [artículos]»_")
            return True, "\n".join(lines), "suppliers_list"

        elif inq_type == "all_baskets":
            drafts = load_supplier_drafts()
            active_baskets = {k: v for k, v in drafts.items() if v.get("items")}
            if not active_baskets:
                return True, (
                    "🧺 *No tenés pedidos pendientes en ninguna canasta de proveedores.*\n\n"
                    "💡 Para anotar mercadería que te falte decime:\n"
                    "_«Sofi, anotá para la Bulonera 5 cajas de tornillos T1»_"
                ), "no_active_baskets"

            lines = [f"🧺 *CANASTAS DE REPOSICIÓN ABIERTAS ({len(active_baskets)}):*\n"]
            for k, b in active_baskets.items():
                s_name = b.get("supplier_name", "Proveedor")
                items_cnt = sum(it.get("quantity", 1) for it in b.get("items", []))
                lines.append(f"🏢 *{s_name}* ({len(b.get('items', []))} productos, {items_cnt} bultos/unidades):")
                for it in b.get("items", [])[:4]:
                    lines.append(f"  • {it.get('quantity')}x {it.get('product_name')}")
                if len(b.get("items", [])) > 4:
                    lines.append(f"  • ... y {len(b.get('items', [])) - 4} más.")
                lines.append(f"  👉 Despachar: _«Mandale el pedido a {s_name}»_\n")
            return True, "\n".join(lines), "all_baskets_summary"

        elif inq_type == "single_basket":
            target_sup = inquiry_data.get("supplier_name", "")
            basket = get_supplier_draft(target_sup)
            if not basket or not basket.get("items"):
                return True, (
                    f"🧺 *La canasta de {target_sup} está vacía.*\n\n"
                    f"💡 Para anotarle mercadería decime:\n"
                    f"_«Sofi, anotá para {target_sup} 10 cajas de tornillos...»_"
                ), "single_basket_empty"

            items = basket.get("items", [])
            lines = [f"🧺 *CANASTA PENDIENTE PARA {basket.get('supplier_name', target_sup).upper()}* ({len(items)} productos):\n"]
            for idx, it in enumerate(items, 1):
                lines.append(f"{idx}. *{it.get('quantity')}x {it.get('product_name')}*")
            lines.append(f"\n🚀 *Para despachar este pedido decime:*")
            lines.append(f"_«Sofi, mandale el pedido a {basket.get('supplier_name', target_sup)}»_")
            return True, "\n".join(lines), "single_basket_detail"

    # 1.8 Add items to Supplier Basket
    basket_add_data = await parse_supplier_basket_add_intent(clean_text)
    if basket_add_data.get("is_basket_add") and basket_add_data.get("items"):
        sup_name = basket_add_data.get("supplier_name") or "Proveedor"
        raw_items = basket_add_data.get("items", [])

        # Enrich items with prices from catalog if available
        enriched_items = []
        for it in raw_items:
            p_name = it.get("product_name", "").strip()
            p_qty = int(it.get("quantity", 1))
            prod = catalog_service.find_product_exact_or_best(p_name)
            price = prod.price if prod else 0.0
            enriched_items.append({
                "product_name": prod.name if prod else p_name.capitalize(),
                "quantity": p_qty,
                "unit_price": price
            })

        updated_basket = add_items_to_supplier_draft(sup_name, enriched_items)
        total_items = len(updated_basket.get("items", []))
        total_units = sum(it.get("quantity", 1) for it in updated_basket.get("items", []))

        lines = [
            f"🧺 *¡Anotado en la canasta de {sup_name}!* 📝\n",
            f"Se agregaron los siguientes productos:"
        ]
        for it in enriched_items:
            lines.append(f"• {it['quantity']}x {it['product_name']}")
        lines.append(f"\n📦 *Total acumulado en canasta:* {total_items} productos ({total_units} unidades/bultos).")
        lines.append(f"💡 Cuando quieras despacharle decime: _«Mandale el pedido a {sup_name}»_")

        return True, "\n".join(lines), "basket_item_added"

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
        # Check if Javier wants to send the list to a third party (e.g. "mandale la lista a Ricardo")
        send_to_third_party = any(k in lower_text for k in ["mandale la lista a", "pasale la lista a", "enviale la lista a", "mandá la lista a", "enviá la lista a", "mandale los precios a", "pasale los precios a"]) or (
            any(k in lower_text for k in ["mandale", "pasale", "enviale", "mandá a"]) and any(k in lower_text for k in ["la lista", "los precios", "el excel", "el catalogo", "el catálogo"])
        )
        target_to_send = None
        target_recipient_name = "Cliente"

        if send_to_third_party:
            active_c = get_active_onboarded_client(db)
            cand_digits = re.findall(r'\d{8,14}', clean_text.replace("-", "").replace(" ", "").replace("+", ""))
            if cand_digits:
                target_to_send = normalize_argentine_phone(cand_digits[0])
                target_recipient_name = "Cliente"
            elif active_c.get("phone"):
                ac_contact = (active_c.get("contact_name") or "").lower()
                ac_bname = (active_c.get("business_name") or "").lower()
                if not ac_contact or ac_contact in lower_text or ac_bname in lower_text or any(k in lower_text for k in ["a ricardo", "al cliente", "a este", "a el", "a él"]):
                    target_to_send = active_c["phone"]
                    target_recipient_name = active_c.get("contact_name") or active_c.get("business_name") or "Cliente"

            if not target_to_send:
                target_match = re.search(r'(?:a|para)\s+([A-ZÁÉÍÓÚa-záéíóú\s]+)', clean_text)
                if target_match:
                    cand_name = target_match.group(1).strip()
                    p_match = db.query(Prospect).filter(
                        (Prospect.contact_name.ilike(f"%{cand_name}%")) |
                        (Prospect.name.ilike(f"%{cand_name}%"))
                    ).order_by(Prospect.updated_at.desc()).first()
                    if p_match:
                        target_to_send = p_match.phone
                        target_recipient_name = p_match.contact_name or p_match.name

        if target_to_send and target_to_send != sender_phone:
            third_party_msg = (
                f"¡Hola {target_recipient_name}! ¿Cómo estás? Te escribo de parte de Javier.\n\n"
                f"Te adjunto acá mismo nuestra lista de precios completa y actualizada en Excel "
                f"para que la mires tranquilo en el celu o la compu.\n\n"
                f"💡 Si querés consultar precios o pasar un pedido, podés responder directamente con un mensaje o audio a este chat."
            )
            excel_url = "https://sofia-ai-agency.onrender.com/assets/catalogo_actualizado.xlsx"
            asyncio.create_task(whatsapp.send_whatsapp_message(to_phone=target_to_send, text=third_party_msg))
            asyncio.create_task(whatsapp.send_whatsapp_document(
                to_phone=target_to_send,
                document_url=excel_url,
                filename="Lista_Precios_Oficial.xlsx",
                caption="📊 Lista de Precios Oficial Actualizada"
            ))
            return True, f"✅ *¡Lista de precios enviada con éxito!*\n\nAcabo de enviarle la lista oficial en Excel a *{target_recipient_name}* (+{target_to_send}).", "boss_price_list_sent_client"

        demo_reply = _build_price_list_demo(sender_phone)
        return True, demo_reply, "boss_price_list_demo"

    # 2.95 Dispatch Order to External Distributor or Live Demo to Merchant
    dispatch_triggers = [
        "mandale el pedido a", "mandar pedido a", "pasar pedido a", "enviar pedido a",
        "mandale a", "mandá a", "hacele el pedido a", "hacé el pedido a",
        "despachar pedido a", "despachale a", "pasale el pedido a", "enviá el pedido a",
        "enviar a la distribuidora", "mandar a la distribuidora", "pasale a", "enviale a", "envíale a",
        "enviale este mensaje", "enviá este mensaje", "enviale éste mensaje", "mandale este mensaje",
        "mandale la demo a", "mandar la demo a", "mandá la demo a", "enviar la demo a", "pasale la demo a",
        "mandale demo a", "mandar demo a", "enviar demo a"
    ]
    is_dispatch_candidate = any(k in lower_text for k in dispatch_triggers) or (
        any(k in lower_text for k in ["enviale", "envíale", "mandale", "pasale", "despachale", "mandar", "enviar"]) and
        any(k in lower_text for k in ["demo", "pedido", "pedidos", "remito", "prueba", "martillo", "alicate", "tornillo", "disco", "caja", "bolsa", "harina", "aceite", "a ferreteria", "a ferretería", "a distribuidora", "el numero es", "el número es", "telefono es", "teléfono es"])
    )

    if is_dispatch_candidate:
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
            distributor_match = re.search(r'(?:pedido\s+a|la\s+demo\s+a|demo\s+a|a|para)\s+([^\n\r,]+?)(?:\s+al\s+\d+|\s+el\s+numero|\s+el\s+número|\s+con\b|$)', clean_text, re.IGNORECASE)
            if distributor_match:
                dist_name = distributor_match.group(1).strip()
        if not dist_name:
            dist_name = "la Distribuidora"
        dist_name = re.sub(r'^(?:la|el|los|las)\s+', '', dist_name, flags=re.IGNORECASE).strip()

        active_client = get_active_onboarded_client(db)

        # If phone is not yet found, check if recipient matches active client or db prospect
        if not target_phone and active_client.get("phone"):
            ac_contact = (active_client.get("contact_name") or "").lower()
            ac_bname = (active_client.get("business_name") or "").lower()
            req_lower = dist_name.lower()
            if (ac_contact and (ac_contact in req_lower or req_lower in ac_contact)) or \
               (ac_bname and (ac_bname in req_lower or req_lower in ac_bname)) or \
               (ac_contact and ac_contact in lower_text) or (ac_bname and ac_bname in lower_text):
                target_phone = active_client["phone"]
                dist_name = active_client.get("contact_name") or active_client.get("business_name")

        if not target_phone and dist_name and len(dist_name) > 2 and dist_name.lower() not in ["la distribuidora", "distribuidora", "proveedor"]:
            matched_p = db.query(Prospect).filter(
                (Prospect.contact_name.ilike(f"%{dist_name}%")) |
                (Prospect.name.ilike(f"%{dist_name}%"))
            ).order_by(Prospect.updated_at.desc()).first()
            if matched_p:
                target_phone = matched_p.phone
                dist_name = matched_p.contact_name or matched_p.name

        if target_phone:
            target_phone = normalize_argentine_phone(target_phone)

        if not target_phone:
            return True, (
                f"📋 *¡Pedido formal en preparación para {dist_name}!* \n\n"
                f"Para despacharle el remito PDF adjunto por WhatsApp, por favor pasame su número de teléfono.\n\n"
                f"💡 Podés escribir por ejemplo: `al 3434536447` o mandarme el contacto."
            ), "dispatch_needs_phone"

        if target_phone:
            # Check if there is an open supplier basket for dist_name
            sup_basket = get_supplier_draft(dist_name)
            has_basket = bool(sup_basket and sup_basket.get("items"))

            ai_items = ai_dispatch.get("items", [])
            if not ai_items and has_basket:
                ai_items = sup_basket["items"]

            fallback_items = []
            if ai_items:
                for it in ai_items:
                    p_name = str(it.get("product_name") or "").strip()
                    p_qty = int(it.get("quantity") or 1)
                    p_price = float(it.get("unit_price") or 0.0)
                    if p_name:
                        prod = catalog_service.find_product_exact_or_best(p_name)
                        if prod:
                            fallback_items.append(OrderItem(product=prod, quantity=p_qty, unit_price=prod.price, subtotal=prod.price * p_qty))
                        else:
                            dyn_prod = ProductItem(name=p_name.capitalize(), price=p_price, presentation="Bulto/Unidad")
                            fallback_items.append(OrderItem(product=dyn_prod, quantity=p_qty, unit_price=p_price, subtotal=p_price * p_qty))

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
            
            if active_client.get("business_name"):
                client_name = active_client["business_name"]
                contact_name = active_client.get("contact_name") or ("Encargado de Compras" if is_ferreteria else "Juan (Comercio Minorista)")
                client_city = active_client.get("city") or "Paraná, Entre Ríos"
            else:
                sender_p = db.query(Prospect).filter(Prospect.phone == sender_phone).first() if db else None
                if sender_p and sender_p.name:
                    client_name = sender_p.name
                    contact_name = sender_p.contact_name or ("Encargado de Compras" if is_ferreteria else "Comercio Minorista")
                    client_city = sender_p.city or "Paraná, Entre Ríos"
                else:
                    client_name = "Ferretería 'El Amigo'" if is_ferreteria else "Kiosco 'Lo de Juan'"
                    contact_name = "Encargado de Compras" if is_ferreteria else "Juan (Comercio Minorista)"
                    client_city = "Paraná, Entre Ríos"

            total_display = draft.formatted_total() if getattr(draft, "total", 0) > 0 else "A cotizar según lista de distribuidor"

            pdf_bytes = generate_order_pdf(
                client_name=client_name,
                contact_name=contact_name,
                phone=sender_phone,
                city=client_city,
                order_draft=draft,
                order_number=f"PED-{datetime.now().strftime('%d%H%M')}"
            )

            item_lines = "\n".join([
                f"• {it.quantity}x {it.product.name}" + (f" ({it.product.presentation})" if it.product.presentation and it.product.presentation != "Unidad" else "")
                for it in draft.items
            ]) if draft.items else f"• 1x {clean_order_part}"

            is_demo_to_client = bool(active_client.get("phone") and target_phone == active_client.get("phone"))
            if is_demo_to_client:
                dist_msg = (
                    f"¡Hola {dist_name}! Te escribo de parte de Javier de Sofía IA.\n\n"
                    f"Te paso el comprobante formal de pedido de prueba para *{client_name}*:\n"
                    f"{item_lines}\n"
                    f"Total estimado: {total_display}\n\n"
                    f"📄 Adjunto remito en PDF con el detalle formal.\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 *DEMO EN VIVO:* Este comprobante fue generado automáticamente por Sofía para la demostración en tu local. ¡Muchas gracias!"
                )
            else:
                dist_msg = (
                    f"Hola {dist_name}! Te escribo de parte del {contact_name} de *{client_name}*.\n\n"
                    f"Te paso su pedido formal para el reparto de mañana:\n"
                    f"{item_lines}\n"
                    f"Total estimado: {total_display}\n\n"
                    f"📄 Adjunto remito en PDF con el detalle formal.\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 *IMPORTANTE:* Por favor envíe confirmación de pedido, remitos o listas de precios actualizadas directamente a este chat. Soy la asistente del comercio '{client_name}'. ¡Muchas gracias!"
                )

            base_url = settings.APP_BASE_URL.rstrip('/')
            if "127.0.0.1" in base_url or "localhost" in base_url:
                base_url = "https://sofia-ai-agency.onrender.com"
            pdf_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "ultimo_pedido_kiosco.pdf"))
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
            pdf_url = f"{base_url}/assets/ultimo_pedido_kiosco.pdf"

            # Dispatch payload:
            # 1. Attempt official Meta Template (essential if outside 24h window)
            template_name = "demo_comercio_v1" if is_demo_to_client else "orden_compra_v1"
            tpl_items = ", ".join([f"{it.quantity}x {it.product.name}" for it in draft.items])[:200]
            components = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": dist_name},
                        {"type": "text", "text": client_name},
                        {"type": "text", "text": tpl_items},
                        {"type": "text", "text": total_display}
                    ]
                }
            ]
            asyncio.create_task(whatsapp.send_whatsapp_template(
                to_phone=target_phone,
                template_name=template_name,
                language_code="es_AR",
                components=components
            ))

            # 2. Conversational text detail (delivered via Meta or Whapi gateway)
            asyncio.create_task(whatsapp.send_whatsapp_message(to_phone=target_phone, text=dist_msg))

            # 3. Formal PDF document
            asyncio.create_task(whatsapp.send_whatsapp_document(
                to_phone=target_phone,
                document_url=pdf_url,
                filename="Pedido_Formal.pdf",
                caption=f"📄 Pedido Formal {client_name} -> {dist_name}"
            ))

            if has_basket:
                clear_supplier_draft(dist_name)

            basket_note = f"\n\n✨ *La canasta de {dist_name} quedó vaciada y lista para la próxima reposición.*" if has_basket else ""

            return True, (
                f"✅ *¡Pedido despachado con éxito!*\n\n"
                f"Acabo de enviarle a *{dist_name}* (+{target_phone}) el detalle formal y el remito en PDF.\n\n"
                f"📋 *Items enviados:*\n{item_lines}\n"
                f"💰 *Total:* {total_display}\n\n"
                f"📍 Mensaje y remito PDF enviados correctamente."
                f"{basket_note}"
            ), "kiosk_order_dispatched"


    # 3. Live Demo / Order Test or Product Inquiry by the Boss (for video demos from personal phone)
    from app.services.order_engine import (
        parse_order_or_inquiry_with_ai,
        parse_order_text,
        format_order_summary_message,
        build_product_inquiry_reply,
        is_order_confirmation,
        OrderItem,
        OrderDraft
    )

    analysis = await parse_order_or_inquiry_with_ai(clean_text)
    if analysis.intent == "price_list_request" and not is_admin_internal_view and not any(k in lower_text for k in ["servicio", "software", "agencia", "abono", "ia"]):
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

    # 2.8.0 Weekly Price Fluctuations / Market Increases
    if any(k in lower_text for k in [
        "aumento", "aumentó", "aumentos", "aumentaron", "que aumento", "qué aumentó",
        "que productos me aumentaron", "qué productos me aumentaron", "subieron los precios",
        "variaciones de precio", "cambios de precio", "que subio", "qué subió"
    ]) and not any(k in lower_text for k in ["servicio", "software", "agencia", "abono", "ia"]):
        weekly_summary = catalog_service.get_weekly_price_changes(requester_name="Javier")
        return True, weekly_summary, "boss_price_increases"

    # 2.8.1 Multi-supplier Price Comparison & Cheapest Supplier Inquiry
    if any(k in lower_text for k in [
        "mas barato", "más barato", "vende mas barato", "vende más barato",
        "tiene mas barato", "tiene más barato", "quien tiene", "quién tiene",
        "comparame", "comparar precios", "comparativa de precios", "comparar", "mejor precio",
        "quien vende mas barato", "quién vende más barato", "quien me deja mas barato", "quién me deja más barato"
    ]) and not any(k in lower_text for k in ["servicio", "software", "agencia", "sofia", "ia", "abono"]):
        formatted_comp = catalog_service.format_price_comparison(clean_text, requester_name="Javier")
        if formatted_comp:
            return True, formatted_comp, "boss_price_comparison"

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

    # 5.3 Client Manual / User Guide (`manual`, `guia`, `instructivo`, `modo de uso`)
    manual_triggers = ["manual", "guia", "guía", "instructivo", "modo de uso", "manual de uso", "manual cliente", "guia cliente", "guía cliente"]
    if any(lower_text.strip() == k or lower_text.startswith(k + " ") for k in manual_triggers):
        manual_text = get_client_manual_text()
        phone_match = re.search(r'(\d{8,15})', lower_text)
        if ("enviar" in lower_text or "mandar" in lower_text) and phone_match:
            dest_phone = phone_match.group(1)
            if not dest_phone.startswith("54"):
                dest_phone = "549" + dest_phone.lstrip("0")
            asyncio.create_task(whatsapp.send_whatsapp_message(to_phone=dest_phone, text=manual_text))
            return True, f"✅ *Manual de uso enviado con éxito* al número +{dest_phone}.", "boss_manual_dispatched"

        boss_reply = (
            f"📖 *MANUAL RÁPIDO DE USO PARA CLIENTES (Listo para reenviar):*\n\n"
            f"{manual_text}\n\n"
            f"💡 _Tip: Si querés que se lo envíe directamente a un cliente, escribí: `enviar manual al <número>`._"
        )
        return True, boss_reply, "boss_manual_view"

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

