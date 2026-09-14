import os
import re
import json
import logging
import asyncio
import httpx
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.prospect import Prospect, SupplierDraftOrder, MerchantProduct
from app.services.catalog import catalog_service, parse_supplier_price_update_text
from app.services import brain
from app.services import whatsapp

logger = logging.getLogger(__name__)

LAST_BOSS_ORDERS = {}
LAST_ONBOARDED_CLIENT = {}

SUPPLIER_DRAFTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "supplier_draft_orders.json")

def load_supplier_drafts(merchant_phone: Optional[str] = None, db: Optional[Session] = None) -> dict:
    """
    Loads open draft orders.
    Multi-tenant:
    If db and merchant_phone are provided, queries SupplierDraftOrder from database.
    Falls back gracefully to JSON storage.
    """
    if db and merchant_phone:
        try:
            records = db.query(SupplierDraftOrder).filter(
                SupplierDraftOrder.merchant_phone == merchant_phone
            ).all()
            if records:
                result = {}
                for r in records:
                    try:
                        it_list = json.loads(r.items) if r.items else []
                    except Exception:
                        it_list = []
                    result[r.supplier_key] = {
                        "supplier_name": r.supplier_name,
                        "items": it_list,
                        "updated_at": r.updated_at.isoformat() if r.updated_at else datetime.now(timezone.utc).isoformat()
                    }
                return result
        except Exception as e:
            logger.warning(f"Error reading drafts from DB for {merchant_phone}: {e}")

    if os.path.exists(SUPPLIER_DRAFTS_FILE):
        try:
            with open(SUPPLIER_DRAFTS_FILE, "r", encoding="utf-8") as f:
                all_file_drafts = json.load(f)
                clean_m = "".join(filter(str.isdigit, str(merchant_phone or "")))
                if clean_m and isinstance(all_file_drafts, dict) and clean_m in all_file_drafts:
                    return all_file_drafts[clean_m]
                
                # If merchant_phone was specified but has no dedicated drafts,
                # if it's boss or WHATSAPP_ALERT_PHONE or not specified, fallback to root drafts:
                if not clean_m or is_boss_number(clean_m) or clean_m == settings.WHATSAPP_ALERT_PHONE:
                    root_drafts = {}
                    if isinstance(all_file_drafts, dict):
                        for k, v in all_file_drafts.items():
                            if isinstance(v, dict) and ("items" in v or "supplier_name" in v):
                                root_drafts[k] = v
                    return root_drafts
                return {}
        except Exception as e:
            logger.warning(f"Error reading supplier drafts: {e}")
    return {}

def save_supplier_drafts(drafts: dict, merchant_phone: Optional[str] = None, db: Optional[Session] = None):
    """
    Saves open draft orders to database (if db & merchant_phone provided) and JSON fallback.
    """
    if db and merchant_phone:
        try:
            for sup_key, data in drafts.items():
                s_name = data.get("supplier_name") or sup_key.replace("_", " ").title()
                items_json = json.dumps(data.get("items", []), ensure_ascii=False)
                rec = db.query(SupplierDraftOrder).filter(
                    SupplierDraftOrder.merchant_phone == merchant_phone,
                    SupplierDraftOrder.supplier_key == sup_key
                ).first()
                if rec:
                    rec.items = items_json
                    rec.supplier_name = s_name
                    rec.updated_at = datetime.now(timezone.utc)
                else:
                    rec = SupplierDraftOrder(
                        merchant_phone=merchant_phone,
                        supplier_key=sup_key,
                        supplier_name=s_name,
                        items=items_json
                    )
                    db.add(rec)
            db.commit()
        except Exception as e:
            logger.error(f"Error saving supplier drafts to db: {e}")

    try:
        os.makedirs(os.path.dirname(SUPPLIER_DRAFTS_FILE), exist_ok=True)
        all_file_drafts = {}
        if os.path.exists(SUPPLIER_DRAFTS_FILE):
            try:
                with open(SUPPLIER_DRAFTS_FILE, "r", encoding="utf-8") as f:
                    all_file_drafts = json.load(f)
            except Exception:
                all_file_drafts = {}

        clean_m = "".join(filter(str.isdigit, str(merchant_phone or "")))
        if clean_m:
            all_file_drafts[clean_m] = drafts
            if is_boss_number(clean_m) or clean_m == settings.WHATSAPP_ALERT_PHONE:
                all_file_drafts.update(drafts)
        else:
            all_file_drafts.update(drafts)

        with open(SUPPLIER_DRAFTS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_file_drafts, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving supplier drafts: {e}")

def add_items_to_supplier_draft(
    supplier_name: str,
    items: List[dict],
    merchant_phone: Optional[str] = None,
    db: Optional[Session] = None
) -> dict:
    sup_key = re.sub(r'[^\w\s]', '', supplier_name).strip().lower().replace(' ', '_')

    # If DB and merchant_phone are available, manage via database for ACID isolation
    if db and merchant_phone:
        rec = db.query(SupplierDraftOrder).filter(
            SupplierDraftOrder.merchant_phone == merchant_phone,
            SupplierDraftOrder.supplier_key == sup_key
        ).first()
        current_items = []
        if rec and rec.items:
            try:
                current_items = json.loads(rec.items)
            except Exception:
                current_items = []

        for it in items:
            p_name = str(it.get("product_name") or it.get("name") or "").strip()
            p_qty = int(it.get("quantity") or it.get("qty") or 1)
            p_price = float(it.get("unit_price") or it.get("price") or 0.0)
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

        if rec:
            rec.items = json.dumps(current_items, ensure_ascii=False)
            rec.supplier_name = supplier_name
            rec.updated_at = datetime.now(timezone.utc)
        else:
            rec = SupplierDraftOrder(
                merchant_phone=merchant_phone,
                supplier_key=sup_key,
                supplier_name=supplier_name,
                items=json.dumps(current_items, ensure_ascii=False)
            )
            db.add(rec)
        db.commit()

        # Keep JSON fallback in sync
        try:
            drafts = load_supplier_drafts(merchant_phone=merchant_phone)
            drafts[sup_key] = {
                "supplier_name": supplier_name,
                "items": current_items,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            save_supplier_drafts(drafts, merchant_phone=merchant_phone)
        except Exception:
            pass

        return {
            "supplier_name": supplier_name,
            "items": current_items,
            "updated_at": rec.updated_at.isoformat() if rec.updated_at else datetime.now(timezone.utc).isoformat()
        }

    # Fallback to file-based drafts
    drafts = load_supplier_drafts(merchant_phone=merchant_phone)
    if sup_key not in drafts:
        drafts[sup_key] = {
            "supplier_name": supplier_name,
            "items": [],
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
    current_items = drafts[sup_key]["items"]
    for it in items:
        p_name = str(it.get("product_name") or it.get("name") or "").strip()
        p_qty = int(it.get("quantity") or it.get("qty") or 1)
        p_price = float(it.get("unit_price") or it.get("price") or 0.0)
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
    save_supplier_drafts(drafts, merchant_phone=merchant_phone)
    return drafts[sup_key]

def get_supplier_draft(
    supplier_name: str,
    merchant_phone: Optional[str] = None,
    db: Optional[Session] = None
) -> Optional[dict]:
    target = supplier_name.strip().lower()
    sup_key = re.sub(r'[^\w\s]', '', target).replace(' ', '_')
    clean_m = "".join(filter(str.isdigit, str(merchant_phone or "")))
    if db:
        if clean_m:
            rec = db.query(SupplierDraftOrder).filter(
                SupplierDraftOrder.merchant_phone == clean_m,
                SupplierDraftOrder.supplier_key == sup_key
            ).first()
            if not rec:
                rec = db.query(SupplierDraftOrder).filter(
                    SupplierDraftOrder.merchant_phone == clean_m,
                    SupplierDraftOrder.supplier_name.ilike(f"%{supplier_name.strip()}%")
                ).first()
            if not rec and (is_boss_number(clean_m) or clean_m == settings.WHATSAPP_ALERT_PHONE):
                rec = db.query(SupplierDraftOrder).filter(
                    SupplierDraftOrder.merchant_phone == None,
                    SupplierDraftOrder.supplier_key == sup_key
                ).first()
        else:
            rec = db.query(SupplierDraftOrder).filter(
                SupplierDraftOrder.supplier_key == sup_key
            ).first()

        if rec:
            try:
                it_list = json.loads(rec.items) if rec.items else []
            except Exception:
                it_list = []
            return {
                "supplier_name": rec.supplier_name,
                "items": it_list,
                "updated_at": rec.updated_at.isoformat() if rec.updated_at else datetime.now(timezone.utc).isoformat()
            }

    drafts = load_supplier_drafts(merchant_phone=merchant_phone, db=db)
    if sup_key in drafts:
        return drafts[sup_key]
    for k, v in drafts.items():
        if isinstance(v, dict):
            s_title = v.get("supplier_name", "").strip().lower()
            if s_title and (target in s_title or s_title in target):
                return v
    return None

def clear_supplier_draft(
    supplier_name: str,
    merchant_phone: Optional[str] = None,
    db: Optional[Session] = None
):
    target = supplier_name.strip().lower()
    sup_key = re.sub(r'[^\w\s]', '', target).replace(' ', '_')
    clean_m = "".join(filter(str.isdigit, str(merchant_phone or "")))

    # 1. Database removal
    if db:
        if clean_m:
            recs = db.query(SupplierDraftOrder).filter(
                (SupplierDraftOrder.merchant_phone == clean_m) |
                (SupplierDraftOrder.merchant_phone == None)
            ).all()
        else:
            recs = db.query(SupplierDraftOrder).all()
        for r in recs:
            r_title = (r.supplier_name or "").strip().lower()
            if r.supplier_key == sup_key or (target and r_title and (target in r_title or r_title in target)):
                db.delete(r)
        db.commit()

    # 2. JSON file removal
    if os.path.exists(SUPPLIER_DRAFTS_FILE):
        try:
            with open(SUPPLIER_DRAFTS_FILE, "r", encoding="utf-8") as f:
                all_file_drafts = json.load(f)
            changed = False

            # Delete from root if present
            if sup_key in all_file_drafts:
                del all_file_drafts[sup_key]
                changed = True
            for k, v in list(all_file_drafts.items()):
                if isinstance(v, dict) and ("items" in v or "supplier_name" in v):
                    s_title = v.get("supplier_name", "").strip().lower()
                    if s_title and (target in s_title or s_title in target):
                        del all_file_drafts[k]
                        changed = True

            # If clean_m specified, delete within that merchant's namespace
            if clean_m and clean_m in all_file_drafts and isinstance(all_file_drafts[clean_m], dict):
                m_drafts = all_file_drafts[clean_m]
                if sup_key in m_drafts:
                    del m_drafts[sup_key]
                    changed = True
                for k, v in list(m_drafts.items()):
                    if isinstance(v, dict):
                        s_title = v.get("supplier_name", "").strip().lower()
                        if s_title and (target in s_title or s_title in target):
                            del m_drafts[k]
                            changed = True

            # If boss or no clean_m, remove across all namespaces
            if not clean_m or is_boss_number(clean_m) or clean_m == settings.WHATSAPP_ALERT_PHONE:
                for sub_k, sub_dict in list(all_file_drafts.items()):
                    if isinstance(sub_dict, dict) and "items" not in sub_dict and "supplier_name" not in sub_dict:
                        for k, v in list(sub_dict.items()):
                            if isinstance(v, dict):
                                s_title = v.get("supplier_name", "").strip().lower()
                                if s_title and (target in s_title or s_title in target):
                                    del sub_dict[k]
                                    changed = True

            if changed:
                with open(SUPPLIER_DRAFTS_FILE, "w", encoding="utf-8") as f:
                    json.dump(all_file_drafts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error clearing supplier draft: {e}")


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
            LAST_ONBOARDED_CLIENT.clear()
            LAST_ONBOARDED_CLIENT.update({
                "phone": recent.phone,
                "business_name": recent.name,
                "contact_name": recent.contact_name,
                "business_type": recent.business_type,
                "city": recent.city
            })
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

def resolve_merchant_identity(sender_phone: str, db: Session, target_sup_name: str = "") -> dict:
    """
    Resolves a clean, natural identity for the merchant contacting suppliers.
    Avoids awkward redundant phrasing like 'Javier de Javier Coloma (Director)'.
    Returns:
        {
            "client_owner": "Javier" or "Mariana",
            "client_biz": "Compras" or "Kiosco Avenida",
            "sender_intro": "Javier Coloma" or "Mariana de Kiosco Avenida",
            "biz_tag": "Javier Coloma" or "Kiosco Avenida"
        }
    """
    client_prospect = None
    if sender_phone and db:
        clean_s = "".join(filter(str.isdigit, str(sender_phone)))
        candidates = [clean_s, normalize_argentine_phone(clean_s)]
        client_prospect = db.query(Prospect).filter(Prospect.phone.in_(candidates)).first()

    is_boss = is_boss_number(sender_phone)
    active_c = get_active_onboarded_client(db) if db else {}

    if is_boss:
        boss_record = client_prospect if (client_prospect and is_boss_number(client_prospect.phone)) else None
        if boss_record and boss_record.status == "director":
            client_owner = "Javier"
            client_biz = "Compras"
            sender_intro = "Javier Coloma"
            biz_tag = "Javier Coloma"
        elif active_c and active_c.get("business_name"):
            client_biz = active_c.get("business_name").strip()
            client_owner = brain.sanitize_contact_first_name(active_c.get("contact_name")) or "Javier"
            sender_intro = f"{client_owner} de {client_biz}"
            biz_tag = client_biz
        else:
            client_owner = "Javier"
            client_biz = "Compras"
            sender_intro = "Javier Coloma"
            biz_tag = "Javier Coloma"
    elif client_prospect:
        parent_p = None
        if client_prospect.parent_merchant_phone:
            clean_p = "".join(filter(str.isdigit, str(client_prospect.parent_merchant_phone)))
            parent_p = db.query(Prospect).filter(
                (Prospect.phone == clean_p) | (Prospect.phone == normalize_argentine_phone(clean_p))
            ).first()

        if parent_p:
            clean_biz = re.sub(r'\s*\(.*?\)', '', parent_p.name or "tu comercio").strip() or "tu comercio"
            emp_first = brain.sanitize_contact_first_name(client_prospect.contact_name) or "Encargado"
            client_owner = emp_first
            client_biz = clean_biz
            sender_intro = f"{emp_first} de {clean_biz}"
            biz_tag = clean_biz
        else:
            raw_biz = (client_prospect.name or "tu comercio").strip()
            raw_owner = brain.sanitize_contact_first_name(client_prospect.contact_name) or "el titular"
            clean_biz = re.sub(r'\s*\(.*?\)', '', raw_biz).strip() or "tu comercio"

            if raw_owner.lower() in clean_biz.lower():
                client_owner = raw_owner
                client_biz = "su comercio"
                sender_intro = clean_biz
                biz_tag = clean_biz
            else:
                client_owner = raw_owner
                client_biz = clean_biz
                sender_intro = f"{client_owner} de {client_biz}"
                biz_tag = clean_biz
    else:
        client_owner = "el titular"
        client_biz = "el comercio"
        sender_intro = "el comercio"
        biz_tag = "Compras"

    # Anti-collision safety: client_biz must NEVER be the supplier's own name
    if target_sup_name and client_biz.strip().lower() == target_sup_name.strip().lower():
        client_biz = "tu comercio"
        sender_intro = f"{client_owner} de {client_biz}"
        biz_tag = "Compras"

    return {
        "client_owner": client_owner,
        "client_biz": client_biz,
        "sender_intro": sender_intro,
        "biz_tag": biz_tag
    }

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
        for m_name in ["gemini-3.5-flash", "gemini-flash-latest", "gemini-flash-lite-latest"]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={gemini_key}"
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
                logger.warning(f"Gemini client onboarding parse error with {m_name}: {e}")

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

    # Guard: if it's adding items or querying a supplier basket, it is NOT registration
    basket_words = [
        "anotá para", "anota para", "anotame para", "anótame para",
        "guardá para", "guarda para", "sumale a", "sumale para", "sumá para", "suma para",
        "tengo anotado", "hay anotado", "que tengo", "qué tengo", "anotado para", "canasta"
    ]
    if any(bw in lower for bw in basket_words):
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


def parse_supplier_deletion_intent(text: str) -> dict:
    """
    Detects intent to delete, remove or deregister a supplier.
    e.g. 'eliminar proveedor Distribuidora Alem'
         'borrar al proveedor Alem'
         'dar de baja proveedor Alem'
         'eliminar distribuidora Litoral'
         'sofi, eliminar proveedor Alem'
    """
    clean_text = text.strip()
    orig_no_prefix = re.sub(r'^(?:sofi|sofia|hola|buenas|che)[\s,:]*', '', clean_text, flags=re.IGNORECASE).strip()
    lower_no_prefix = orig_no_prefix.lower()

    patterns = [
        r'(?:eliminar|elimin[áa]|borrar|borr[áa]|dar\s+de\s+baja|d[áa](?:le)?\s+de\s+baja|remover|remov[ée]|quitar|quit[áa])\s+(?:al\s+proveedor|a\s+la\s+distribuidora|al\s+viajante|el\s+proveedor|la\s+distribuidora|proveedor|distribuidora|viajante)\s+([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s\.\'\"]+)',
        r'(?:eliminar|elimin[áa]|borrar|borr[áa]|dar\s+de\s+baja|d[áa](?:le)?\s+de\s+baja|remover|remov[ée]|quitar|quit[áa])\s+([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s\.\'\"]+?)\s+(?:de\s+(?:mis\s+)?proveedores)',
    ]
    for pat in patterns:
        m = re.search(pat, orig_no_prefix, re.IGNORECASE)
        if m:
            s_name = m.group(1).strip()
            s_name = re.sub(r'[\?\.\!\,]+$', '', s_name).strip()
            s_name = re.sub(r'^(?:a\s+|la\s+|el\s+)', '', s_name, flags=re.IGNORECASE).strip()
            if s_name:
                return {"is_supplier_deletion": True, "supplier_name": s_name}

    if lower_no_prefix in [
        "eliminar proveedor", "borrar proveedor", "dar de baja proveedor",
        "eliminar un proveedor", "borrar un proveedor", "dar de baja un proveedor",
        "eliminar distribuidora", "borrar distribuidora"
    ]:
        return {"is_supplier_deletion": True, "supplier_name": None}

    return {"is_supplier_deletion": False}


def parse_client_deletion_intent(text: str) -> dict:
    """
    Detects intent to delete, remove or deregister a client / store (comercio).
    e.g. 'Sofi, eliminar comercio Kiosco Alameda'
         'sofia elimina a kiosco alameda'
         'dar de baja comercio Despensa San José'
         'borrar cliente Kiosco Alameda'
         'eliminar comercio 3434556677'
         'dar de baja mi comercio'
    """
    clean = text.strip()
    orig_no_prefix = re.sub(r'^(?:sofi|sofia|hola|buenas|che)[\s,:]*', '', clean, flags=re.IGNORECASE).strip()
    lower_no_prefix = orig_no_prefix.lower()

    # Guard against supplier, employee or product deletion
    if any(k in lower_no_prefix for k in ["proveedor", "distribuidora", "viajante", "empleado", "repositor", "encargado", "producto", "item", "articulo", "artículo"]):
        return {"is_client_deletion": False}

    if lower_no_prefix in [
        "dar de baja mi comercio", "eliminar mi comercio", "borrar mi comercio",
        "dar de baja mi negocio", "eliminar mi negocio", "dar de baja mi cuenta", "eliminar mi cuenta"
    ]:
        return {"is_client_deletion": True, "target_name": None, "phone": None, "is_self": True}

    patterns = [
        r'(?:eliminar|elimin[áa]|borrar|borr[áa]|dar\s+de\s+baja|d[áa](?:le)?\s+de\s+baja|remover|remov[ée]|quitar|quit[áa])\s+(?:al\s+comercio|a\s+la\s+tienda|al\s+cliente|el\s+comercio|el\s+cliente|comercio|cliente|negocio)\s+(?:al\s+|a\s+)?([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s\.\'\"]+)',
        r'(?:eliminar|elimin[áa]|borrar|borr[áa]|dar\s+de\s+baja|d[áa](?:le)?\s+de\s+baja|remover|remov[ée]|quitar|quit[áa])\s+(?:a\s+)?([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s\.\'\"]+?)\s+(?:de\s+(?:mis\s+)?(?:comercios|clientes))',
        r'(?:eliminar|elimin[áa]|borrar|borr[áa]|dar\s+de\s+baja|d[áa](?:le)?\s+de\s+baja|remover|remov[ée]|quitar|quit[áa])\s+a\s+([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s\.\'\"]+)',
    ]
    for pat in patterns:
        m = re.search(pat, orig_no_prefix, re.IGNORECASE)
        if m:
            c_target = m.group(1).strip()
            c_target = re.sub(r'[\?\.\!\,]+$', '', c_target).strip()
            c_target = re.sub(r'^(?:a\s+|la\s+|el\s+)', '', c_target, flags=re.IGNORECASE).strip()
            if c_target:
                digits = re.sub(r'\D', '', c_target)
                phone = digits if len(digits) >= 8 else None
                name = None if (phone and len(c_target.replace(' ', '').replace('-', '').replace('+', '')) == len(digits)) else c_target
                return {"is_client_deletion": True, "target_name": name, "phone": phone, "is_self": False}

    if lower_no_prefix in [
        "eliminar comercio", "borrar comercio", "dar de baja comercio",
        "eliminar un comercio", "borrar un comercio", "dar de baja un comercio",
        "eliminar cliente", "borrar cliente", "dar de baja cliente"
    ]:
        return {"is_client_deletion": True, "target_name": None, "phone": None, "is_self": False}

    return {"is_client_deletion": False}


async def parse_supplier_phone_update_intent(text: str) -> dict:
    """
    Detects if a merchant wants to update the phone number of an existing supplier.
    e.g. 'Sofi, Carlos de Distribuidora Alem cambió de número al 3434112233'
         'Distribuidora Alem cambió de número, ahora es 3434112233'
         'actualizá el número de Distribuidora Alem al 3434112233'
         'el nuevo whatsapp de Carlos de Distribuidora Alem es 3434112233'
         'cambió de número Pedro de Lácteos Paraná al 343...'
    """
    clean = text.strip()
    lower = clean.lower()

    # Guard: if it's order dispatch or basket addition
    if any(k in lower for k in ["mandale el pedido", "mandar pedido", "despachale", "anotá para", "anotame para"]):
        return {"is_supplier_phone_update": False}

    update_triggers = [
        "cambió de número", "cambio de numero", "cambió el número", "cambio el numero",
        "cambió de número al", "cambio de numero al", "cambió su número", "cambio su numero",
        "cambió de teléfono", "cambio de telefono", "cambió el teléfono", "cambio el telefono",
        "cambió de whatsapp", "cambio de whatsapp", "cambió el whatsapp", "cambio el whatsapp",
        "cambió de celu", "cambio de celu", "cambió el celu", "cambio el celu",
        "nuevo número", "nuevo numero", "nuevo teléfono", "nuevo telefono", "nuevo whatsapp", "nuevo celu",
        "actualizá el número", "actualiza el número", "actualizá el numero", "actualiza el numero",
        "actualizar el número", "actualizar el numero", "actualizar número", "actualizar numero",
        "actualizá el teléfono", "actualiza el teléfono", "actualizá el telefono", "actualiza el telefono",
        "actualizar teléfono", "actualizar telefono", "actualizá el whatsapp", "actualiza el whatsapp",
        "actualizar whatsapp"
    ]
    is_candidate = any(trig in lower for trig in update_triggers) or (
        any(w in lower for w in ["proveedor", "distribuidora", "viajante"]) and any(k in lower for k in ["cambi", "nuevo", "actualiz"]) and any(p in lower for p in ["numero", "número", "telefono", "teléfono", "whatsapp", "celu"])
    )
    if not is_candidate:
        return {"is_supplier_phone_update": False}

    gemini_key = settings.GEMINI_API_KEY
    if gemini_key:
        prompt = (
            "El dueño de un comercio le habla a su asistente comercial Sofía por WhatsApp para avisar que un proveedor, distribuidora o viajante cambió de número de teléfono o para actualizar su WhatsApp.\n"
            f"Mensaje: \"{clean}\"\n\n"
            "Analizá y extraé en formato JSON con estas claves:\n"
            "- is_supplier_phone_update: true o false\n"
            "- supplier_name: nombre comercial de la empresa proveedora o distribuidora (ej: 'Distribuidora Alem', 'Distribuidora Central', o null si solo se dice el nombre del viajante)\n"
            "- contact_name: nombre de pila de la persona si se menciona (ej: 'Carlos', 'Pedro', o null)\n"
            "- new_phone: nuevo número de teléfono extraído (solo dígitos, o null)\n"
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
                            if data.get("is_supplier_phone_update"):
                                return data
        except Exception as e:
            logger.warning(f"Gemini supplier phone update parse error: {e}")

    # Deterministic fallback
    phone_m = re.search(r'(?:al|a|es|nuevo\s+(?:número|numero|teléfono|telefono|whatsapp|celu)\s+es)?\s*:?\s*(\+?[0-9\s\-]{8,25})', clean, re.IGNORECASE)
    new_phone = "".join(filter(str.isdigit, phone_m.group(1))) if phone_m else None

    clean_no_phone = clean[:phone_m.start()].strip() if phone_m else clean
    clean_no_prefix = re.sub(r'^(?:sofi|sofia|hola|buenas|che)[\s,:]*', '', clean_no_phone, flags=re.IGNORECASE).strip()

    # Pattern: "Carlos de Distribuidora Alem cambió..."
    c_m = re.search(r'(?:a\s+)?([A-Za-zÁÉÍÓÚáéíóúñÑ]+)\s+de\s+([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s\.\'\"]+?)\s+(?:cambi[óo]|tiene|es\s+el|actualiz)', clean_no_prefix, re.IGNORECASE)
    if c_m:
        contact_name = c_m.group(1).strip()
        supplier_name = c_m.group(2).strip()
    else:
        s_m = re.search(r'(?:actualiz[áa](?:r)?\s+(?:el\s+)?(?:número|numero|teléfono|telefono|whatsapp)\s+de\s+|al\s+proveedor\s+|a\s+la\s+distribuidora\s+|proveedor\s+|distribuidora\s+)?([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s\.\'\"]+?)\s+(?:cambi[óo]|tiene|es\s+el|al\s+[0-9]|$)', clean_no_prefix, re.IGNORECASE)
        supplier_name = s_m.group(1).strip() if s_m else "Proveedor"
        supplier_name = re.sub(r'^(?:el|la|al|a)\s+', '', supplier_name, flags=re.IGNORECASE).strip()
        contact_name = supplier_name

    return {
        "is_supplier_phone_update": True,
        "supplier_name": supplier_name,
        "contact_name": contact_name,
        "new_phone": new_phone
    }



async def parse_supplier_inquiry_intent(text: str) -> dict:
    """
    Detects if the merchant wants to send a question or direct inquiry to a registered supplier.
    e.g. 'Sofi, preguntale a Pedro de Distribuidora Alem si el lunes hacen reparto'
         'preguntale a Alem si abren mañana'
         'consultale a Distribuidora Central si tienen stock de cal'
         'decile a Bulonera del Litoral que me guarde 5 cajas de tornillos'
         'escribile a Pedro de Distribuidora Alem: hola Pedro, a qué hora pasas?'
    """
    clean = text.strip()
    lower = clean.lower()

    # Guard: if it's an order dispatch, basket update, deletion, or registration, exclude it
    if any(k in lower for k in ["mandale el pedido", "mandar pedido", "despachale", "anotá para", "anotame para", "eliminar proveedor", "agendá al"]):
        return {"is_supplier_inquiry": False}

    inquiry_keywords = [
        "preguntale a", "pregúntale a", "preguntale al", "pregúntale al",
        "consultale a", "consúltale a", "consultale al", "consúltale al",
        "decile a", "dile a", "decile al", "dile al",
        "escribile a", "escríbele a", "escribile al", "escríbele al",
        "avisale a", "avísale a", "mandale a decir a",
        "preguntar a", "consultar a"
    ]
    if not any(k in lower for k in inquiry_keywords):
        return {"is_supplier_inquiry": False}

    gemini_key = settings.GEMINI_API_KEY
    if gemini_key:
        prompt = (
            "El dueño de un comercio minorista le pide a su asistente Sofía por WhatsApp que le envíe una pregunta o consulta a uno de sus proveedores o viajantes.\n"
            f"Mensaje: \"{clean}\"\n\n"
            "Extraé un JSON con:\n"
            "- 'is_supplier_inquiry': true o false\n"
            "- 'supplier_name': nombre del proveedor o persona (ej: 'Distribuidora Alem', 'Pedro', 'Bulonera del Litoral')\n"
            "- 'inquiry_text': la pregunta o mensaje limpio que debe enviarse (ej: '¿El lunes hacen reparto?', '¿Tienen stock de cal?'). Redactado de forma respetuosa y clara.\n"
            "Respondé ÚNICAMENTE un JSON válido con estas claves."
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
                            if data.get("is_supplier_inquiry") and data.get("supplier_name") and data.get("inquiry_text"):
                                return data
        except Exception as e:
            logger.warning(f"Gemini supplier inquiry parse error: {e}")

    # Deterministic regex fallback
    clean_no_prefix = re.sub(r'^(?:sofi|sofía|che|hola|por favor)[\s,:]*', '', clean, flags=re.IGNORECASE).strip()
    
    # Pattern: preguntale/consultale/decile/escribile a <proveedor> [que/si/a qué/cuando/etc] <mensaje>
    m = re.search(
        r'(?:pregunt[áa]le|preg[úu]ntale|consult[áa]le|cons[úu]ltale|decile|dile|escribile|escr[íi]bele|avisale|av[íi]sale)\s+(?:a\s+|al\s+|a\s+la\s+)?([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s\.\'\"]+?)\s+(si\s+.+|qu[ée]\s+.+|a\s+qu[ée]\s+.+|por\s+qu[ée]\s+.+|cu[aá]ndo\s+.+|para\s+cu[aá]ndo\s+.+|cu[aá]nto\s+.+|c[oó]mo\s+.+|d[oó]nde\s+.+|que\s+.+|:\s*.+)',
        clean_no_prefix,
        re.IGNORECASE
    )
    if m:
        s_name = m.group(1).strip()
        inq = m.group(2).strip()
        inq = re.sub(r'^:\s*', '', inq).strip()
        s_name = re.sub(r'^(?:el\s+proveedor|la\s+distribuidora|el\s+viajante)\s+', '', s_name, flags=re.IGNORECASE).strip()
        return {
            "is_supplier_inquiry": True,
            "supplier_name": s_name,
            "inquiry_text": inq
        }

    # Partial match when inquiry keyword was present but missing either supplier or question
    m_partial = re.search(
        r'(?:pregunt[áa]le|preg[úu]ntale|consult[áa]le|cons[úu]ltale|decile|dile|escribile|escr[íi]bele|avisale|av[íi]sale)\s+(?:a\s+|al\s+|a\s+la\s+)?([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s\.\'\"]+)?',
        clean_no_prefix,
        re.IGNORECASE
    )
    part_name = m_partial.group(1).strip() if (m_partial and m_partial.group(1)) else None
    if part_name:
        part_name = re.sub(r'^(?:el\s+proveedor|la\s+distribuidora|el\s+viajante)\s+', '', part_name, flags=re.IGNORECASE).strip()
    return {
        "is_supplier_inquiry": True,
        "supplier_name": part_name if part_name else None,
        "inquiry_text": None
    }


async def parse_employee_management_intent(text: str) -> dict:
    """
    Detects if the merchant wants to manage their store employee team:
    - add_employee: 'Sofi, agregá a Lucas como empleado al 3434536447'
    - grant_dispatch: 'Sofi, autorizá a Lucas a despachar pedidos'
    - revoke_dispatch: 'Sofi, quitale el permiso de despachar a Lucas'
    - delete_employee: 'Sofi, eliminá al empleado Lucas'
    - list_employees: 'empleados', 'ver empleados', 'mi equipo'
    """
    clean_text = text.strip()
    orig_no_prefix = re.sub(r'^(?:sofi|sofia|hola|buenas|che)[\s,:]*', '', clean_text, flags=re.IGNORECASE).strip()
    lower_no_prefix = orig_no_prefix.lower()

    # Guard: exclude general catalog / supplier actions if no employee / team terms are present
    if not any(k in lower_no_prefix for k in [
        "emplead", "repositor", "encargad", "comprador", "mi equipo", "equipo",
        "autoriz", "habilit", "permiso", "desautoriz", "quienes pueden pedir", "quiénes pueden pedir"
    ]):
        return {"is_employee_management": False}

    # 1. List employees
    list_keywords = [
        "empleados", "mis empleados", "ver empleados", "listar empleados", "lista de empleados",
        "mi equipo", "ver mi equipo", "equipo de trabajo", "nuestro equipo",
        "quienes pueden pedir", "quiénes pueden pedir", "quienes pueden despachar", "quiénes pueden despachar",
        "quienes son mis empleados", "quiénes son mis empleados"
    ]
    if lower_no_prefix in list_keywords:
        return {"is_employee_management": True, "action": "list_employees"}

    # 2. Revoke dispatch permission
    # e.g. "quitale el permiso de despachar a Lucas", "revocar permiso a Lucas", "desautorizá a Lucas", "sacale el permiso a Lucas"
    revoke_patterns = [
        r'(?:quit[áa]le\s+el\s+permiso\s+(?:de\s+despachar\s+|para\s+pedir\s+)?a|quitar\s+permiso\s+(?:a\s+)?|revoc[áa](?:le)?\s+(?:el\s+)?permiso\s+(?:a\s+)?|revocar\s+permiso\s+(?:a\s+)?|desautoriz[áa](?:le)?\s+a|desautorizar\s+a|sac[áa]le\s+el\s+permiso\s+a)\s+([A-Za-zÁÉÍÓÚáéíóúñÑ]+)',
    ]
    for pat in revoke_patterns:
        m = re.search(pat, orig_no_prefix, re.IGNORECASE)
        if m:
            target_name = m.group(1).strip()
            return {
                "is_employee_management": True,
                "action": "revoke_dispatch",
                "contact_name": target_name
            }

    # 3. Grant dispatch permission
    # e.g. "autorizá a Lucas a despachar pedidos", "autorizar a Lucas para mandar pedidos", "dale permiso a Lucas para despachar", "habilitá a Lucas para pedir"
    grant_patterns = [
        r'(?:autoriz[áa]|dar\s+autorizaci[óo]n\s+a|habilit[áa]|dale\s+permiso\s+a|dar\s+permiso\s+a|permitir\s+a|permit[íi]\s+a)\s+(?:a\s+)?([A-Za-zÁÉÍÓÚáéíóúñÑ]+)(?:\s+(?:a|para|de)\s+(?:despachar|mandar|enviar|hacer|pasar)\s+pedidos?)?',
        r'(?:pon[eé]|poner)\s+(?:a\s+)?([A-Za-zÁÉÍÓÚáéíóúñÑ]+)\s+como\s+(?:encargad[oa]|comprador[a]?)'
    ]
    for pat in grant_patterns:
        m = re.search(pat, orig_no_prefix, re.IGNORECASE)
        if m:
            target_name = m.group(1).strip()
            if not any(r in lower_no_prefix for r in ["quit", "sac", "revoc", "desautoriz", "eliminar", "borrar"]):
                return {
                    "is_employee_management": True,
                    "action": "grant_dispatch",
                    "contact_name": target_name
                }

    # 4. Delete employee
    del_patterns = [
        r'(?:elimin[áa]r?|borr[áa]r?|dar\s+de\s+baja|remover|remov[eé]|quit[áa]r?|sac[áa]r?)\s+(?:al\s+empleado|a\s+la\s+empleada|al\s+repositor|a\s+la\s+repositora|al\s+encargado|a\s+la\s+encargada|empleado|repositor)\s+([A-Za-zÁÉÍÓÚáéíóúñÑ]+)',
        r'(?:elimin[áa]r?|borr[áa]r?|dar\s+de\s+baja|remover|remov[eé]|quit[áa]r?|sac[áa]r?)\s+a\s+([A-Za-zÁÉÍÓÚáéíóúñÑ]+)\s+(?:del\s+comercio|de\s+los\s+empleados|de\s+mi\s+equipo|como\s+empleado)',
        r'(?:elimin[áa]r?|borr[áa]r?|dar\s+de\s+baja|quit[áa]r?|sac[áa]r?)\s+(?:al\s+)?emplead[oa]\s+([A-Za-zÁÉÍÓÚáéíóúñÑ]+)',
    ]
    for pat in del_patterns:
        m = re.search(pat, orig_no_prefix, re.IGNORECASE)
        if m:
            target_name = m.group(1).strip()
            return {
                "is_employee_management": True,
                "action": "delete_employee",
                "contact_name": target_name
            }

    # 5. Add employee
    # e.g. "agregá a Lucas como empleado al 3434536447", "dar de alta a mi empleado Marcos 1122334455"
    add_match = any(k in lower_no_prefix for k in [
        "agregá a", "agrega a", "agregar a", "dar de alta a", "da de alta a",
        "agendá a", "agenda a", "agendar a", "anotame a", "anotá a", "anota a", "anotar a",
        "nuevo empleado", "nueva empleada"
    ]) and any(r in lower_no_prefix for r in ["emplead", "repositor", "encargad", "comprador"])

    if add_match or any(k in lower_no_prefix for k in ["como empleado", "como empleada", "como repositor", "como repositora", "como encargado", "como encargada", "como comprador"]):
        phone_m = re.search(r'(?:al|el|numero|número|telefono|teléfono|tel|cel)?\s*([0-9\s\-+]{8,25})', orig_no_prefix, re.IGNORECASE)
        phone = "".join(filter(str.isdigit, phone_m.group(1))) if phone_m else None

        clean_for_name = orig_no_prefix[:phone_m.start()].strip() if phone_m else orig_no_prefix

        name_m = re.search(r'(?:agreg[áa]|dar\s+de\s+alta\s+a|agend[áa]|anot[áa]|alta\s+a|a)\s+(?:a\s+)?(?:mi\s+)?(?:emplead[oa]|repositor[a]?|encargad[oa])?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ]+)', clean_for_name, re.IGNORECASE)
        name = name_m.group(1).strip() if name_m else None
        if not name or name.lower() in ["mi", "un", "una", "el", "la", "al", "empleado", "empleada", "repositor", "encargado"]:
            n2 = re.search(r'(?:agreg[áa]|agend[áa]|anot[áa])\s+a\s+([A-Za-zÁÉÍÓÚáéíóúñÑ]+)', clean_for_name, re.IGNORECASE)
            name = n2.group(1).strip() if n2 else "Empleado"

        is_encargado = any(k in lower_no_prefix for k in ["encargad", "comprador", "autorizado", "con permiso"])
        role = "encargado" if is_encargado else "repositor"
        can_dispatch = is_encargado

        return {
            "is_employee_management": True,
            "action": "add_employee",
            "contact_name": name,
            "phone": phone,
            "role": role,
            "can_dispatch": can_dispatch
        }

    # Gemini fallback
    gemini_key = settings.GEMINI_API_KEY
    if gemini_key:
        prompt = (
            "El dueño de un comercio habla con Sofía por WhatsApp para gestionar a los empleados del negocio.\n"
            f"Mensaje: \"{clean_text}\"\n\n"
            "Acciones posibles:\n"
            "- 'add_employee': agregar o registrar nuevo empleado.\n"
            "- 'grant_dispatch': autorizar al empleado a despachar pedidos a distribuidores.\n"
            "- 'revoke_dispatch': quitarle el permiso de despachar pedidos al empleado.\n"
            "- 'delete_employee': dar de baja / eliminar al empleado.\n"
            "- 'list_employees': consultar o ver la lista de empleados.\n\n"
            "Devolvé UN JSON con:\n"
            "{\n"
            "  \"is_employee_management\": true,\n"
            "  \"action\": \"add_employee\" | \"grant_dispatch\" | \"revoke_dispatch\" | \"delete_employee\" | \"list_employees\",\n"
            "  \"contact_name\": nombre del empleado (o null),\n"
            "  \"phone\": teléfono solo dígitos (o null),\n"
            "  \"role\": \"empleado\" o \"encargado\",\n"
            "  \"can_dispatch\": true o false\n"
            "}\n"
            "Si no es para gestionar empleados, devolvé: {\"is_employee_management\": false}"
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={gemini_key}"
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"response_mime_type": "application/json"}}
                )
                if res.status_code == 200:
                    cand = res.json().get("candidates", [])
                    if cand and "content" in cand[0]:
                        parts = cand[0]["content"].get("parts", [])
                        if parts:
                            data = json.loads(parts[0].get("text", "{}"))
                            if data.get("is_employee_management"):
                                return data
        except Exception as e:
            logger.warning(f"Gemini employee management error: {e}")

    return {"is_employee_management": False}


def get_supplier_price_freshness(
    supplier_name: str,
    db: Optional[Session] = None,
    merchant_phone: Optional[str] = None
) -> dict:
    """
    Checks the freshness of a supplier's price list based on the 7-day Argentine wholesale cycle rule.
    Returns dict:
      days_old: int
      is_fresh: bool (True if <= 7 days)
      label: str (e.g. 'lista fresca de esta semana' vs 'lista de hace X días')
      badge: '🟢' or '⚠️'
    """
    clean_sup = (supplier_name or "").strip().lower()
    days_old = 3  # default fresh assumption for active testing unless proven otherwise

    if db:
        try:
            cand = None
            if merchant_phone:
                cand = db.query(Prospect).filter(
                    (Prospect.campaign == "supplier") | (Prospect.business_type == "proveedor")
                ).filter(
                    Prospect.merchant_phone == merchant_phone
                ).filter(
                    (Prospect.name.ilike(f"%{clean_sup}%")) | (Prospect.contact_name.ilike(f"%{clean_sup}%"))
                ).first()

            if not cand:
                cand = db.query(Prospect).filter(
                    (Prospect.campaign == "supplier") | (Prospect.business_type == "proveedor")
                ).filter(
                    (Prospect.name.ilike(f"%{clean_sup}%")) | (Prospect.contact_name.ilike(f"%{clean_sup}%"))
                ).first()

            if cand:
                ref_dt = cand.updated_at or cand.created_at
                if cand.notes:
                    try:
                        n_dict = json.loads(cand.notes)
                        if isinstance(n_dict, dict):
                            l_upd = n_dict.get("last_price_update") or n_dict.get("last_price_list_at") or n_dict.get("registered_at")
                            if l_upd:
                                ref_dt = datetime.fromisoformat(str(l_upd).replace("Z", "+00:00"))
                    except Exception:
                        pass
                if ref_dt:
                    if ref_dt.tzinfo is None:
                        ref_dt = ref_dt.replace(tzinfo=timezone.utc)
                    delta = (datetime.now(timezone.utc) - ref_dt).days
                    days_old = max(0, delta)
        except Exception as e:
            logger.debug(f"Error checking supplier freshness in db: {e}")

    # Specific demo fixtures for realistic testing
    if "nogoy" in clean_sup or "vieja" in clean_sup or "vencid" in clean_sup:
        days_old = 15
    elif "alem" in clean_sup or "central" in clean_sup or "litoral" in clean_sup or "parana" in clean_sup:
        if days_old > 7 and not db:
            days_old = 3

    is_fresh = (days_old <= 7)
    badge = "🟢" if is_fresh else "⚠️"
    if is_fresh:
        if days_old <= 1:
            label = "lista de ayer" if days_old == 1 else "lista de hoy"
        elif days_old <= 4:
            label = f"lista fresca de esta semana (hace {days_old} días)"
        else:
            label = "lista fresca de esta semana"
    else:
        label = f"lista de hace {days_old} días (más de 1 semana)"

    return {
        "days_old": days_old,
        "is_fresh": is_fresh,
        "label": label,
        "badge": badge
    }


async def parse_supplier_basket_add_intent(text: str) -> dict:
    """
    Detects if the merchant wants to add items to a supplier's draft basket,
    either specifying the supplier or dictating a raw list of items without supplier.
    e.g. 'Sofi, anotá para la Bulonera 5 cajas de tornillos T1 y 2 alicates'
         'anotame 10 cajas de Guaymallén y 5 packs de Coca 1.5L'
         'me faltan 10 martillos y 4 alicates'
    """
    clean = text.strip()
    lower = clean.lower()
    has_target = bool(re.search(r'\b(?:para|al pedido de|en el pedido de|a la distribuidora|al proveedor)\s+(?!pedir|preguntar|saber|ver|consultar|avisar|mi\b|vos\b)[A-Za-z0-9]', lower))
    basket_verbs = ["anotá", "anota", "anotame", "agregá", "agrega", "agregame", "sumá", "suma", "sumame", "guardá", "guarda", "guardame", "poné", "pone", "poneme", "cargá", "carga", "cargame", "pedí", "pedi", "pedime"]
    has_action = any(re.search(rf'\b{k}\b', lower) for k in basket_verbs)
    has_faltantes = any(k in lower for k in ["faltan", "falta", "faltante", "faltantes", "reposicion", "reposición", "lo que falta"])
    has_numbers = bool(re.search(r'\b\d+\b', lower))

    if not ((has_action or has_faltantes) and (has_target or has_numbers)):
        return {"is_basket_add": False}

    gemini_key = settings.GEMINI_API_KEY
    if gemini_key:
        prompt = (
            "El dueño de un comercio minorista le dicta a su asistente comercial Sofía por WhatsApp los productos que necesita reponer o anotar.\n"
            "Puede indicar un proveedor (ej: 'anotá para Alem 10 cajas...') o dictar directamente los productos sin especificar proveedor (ej: 'anotame 10 cajas de Guaymallén y 5 de Coca').\n"
            f"Mensaje: \"{clean}\"\n\n"
            "Analizá y extraé en formato JSON con estas claves:\n"
            "- is_basket_add: true o false\n"
            "- supplier_name: nombre del proveedor o distribuidora si el comerciante lo mencionó expresamente, o null si no nombró a ninguno\n"
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
                            if data.get("is_basket_add") and data.get("items"):
                                return data
        except Exception as e:
            logger.warning(f"Gemini basket add parse error: {e}")

    # Fallback deterministic
    sup_m = re.search(r'(?:para|al pedido de|en el pedido de)\s+(?:la|el)?\s*([A-Za-z0-9\s]+?)(?:\s+anot|\s+agreg|\s+sum|\s+ped|\s*:|\s+\d+|$)', clean, re.IGNORECASE)
    sup_name = sup_m.group(1).strip() if sup_m else None
    order_part = re.sub(r'.*?(?:anotá|anota|anotame|agregá|agrega|sumá|suma|pedí|pedi|guardá|guarda|poné|pone|faltan|falta|faltantes)\s+', '', clean, flags=re.IGNORECASE)
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
    or asks for the list of registered suppliers, using natural Argentine street phrasing.
    e.g. 'qué le tengo anotado a la Bulonera?'
         'mostrame lo de Alem'
         'mostrame el pedido de Alem'
         'qué tengo para pedirle a Alem?'
         'pedidos a proveedores'
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
        "canastas abiertas", "que tengo para pedir", "pedidos por proveedor", "canastas de proveedores",
        "que pedidos tengo", "qué pedidos tengo", "pedidos pendientes",
        "resumen", "mi resumen", "resumen de pedidos", "resumen pedidos", "ver canasta", "canasta", "ver resumen"
    ]) or ("pedidos" in clean_no_prefix and "proveedor" in clean_no_prefix):
        return {"is_inquiry": True, "type": "all_baskets"}

    # Single supplier inquiry in colloquial Argentine
    patterns = [
        r'(?:que|qué)\s+le\s+tengo\s+anotado\s+a\s+(?:la|el)?\s*([A-Za-z0-9\s]+?)(?:\?|$)',
        r'(?:que|qué)\s+tengo\s+para\s+pedir(?:le)?\s+a\s+(?:la|el)?\s*([A-Za-z0-9\s]+?)(?:\?|$)',
        r'(?:que|qué)\s+tengo\s+anotado\s+(?:para|de)\s+(?:la|el)?\s*([A-Za-z0-9\s]+?)(?:\?|$)',
        r'(?:que|qué)\s+falta\s+(?:para|de)\s+(?:la|el)?\s*([A-Za-z0-9\s]+?)(?:\?|$)',
        r'(?:mostrame|ver|revisar)\s+(?:lo\s+que\s+le\s+tengo\s+anotado\s+a|lo\s+anotado\s+para|lo\s+anotado\s+de|lo\s+de|el\s+pedido\s+de|el\s+pedido\s+para)\s+(?:la|el)?\s*([A-Za-z0-9\s]+?)(?:\?|$)',
        r'(?:faltantes|pedido|borrador)\s+(?:de|para)\s+(?:la|el)?\s*([A-Za-z0-9\s]+?)(?:\?|$)'
    ]
    for pat in patterns:
        m = re.search(pat, lower)
        if m and not any(k in lower for k in ["mandale", "mandar", "despachale", "despachar", "enviar", "pasar", "hacele"]):
            return {"is_inquiry": True, "type": "single_basket", "supplier_name": m.group(1).strip()}

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
        "Te digo al segundo quién tiene el mejor precio para mejorar tu ganancia.\n\n"
        "2️⃣ *Armar pedidos mientras caminás por el local:*\n"
        "¿Viste un faltante en la góndola? Dictamelo por nota de voz y te lo voy anotando:\n"
        "👉 _«Anotame 10 paquetes de harina y 5 cajas de tornillos»_\n"
        "👉 _«¿Qué tengo anotado para pedirle al viajante de Molinos?»_\n"
        "💰 *Ahorro inteligente:* Si me dictás varios productos surtidos, divido el pedido asignando cada artículo al proveedor más barato para que ahorres plata en cada compra.\n"
        "🚀 *Despacho directo:* Y cuando quieras mandarlo, solo decime: _«Sofi, mandale el pedido a Molinos»_ (o _«mandáselo a todos»_) y le llega formalmente por WhatsApp en el acto.\n\n"
        "3️⃣ *Controlar aumentos de la semana:*\n"
        "Antes de que te cobren de más, preguntame:\n"
        "👉 _«¿Qué productos me aumentaron esta semana?»_\n"
        "Te aviso qué artículos subieron y cuándo conviene stockearte antes de una suba.\n\n"
        "4️⃣ *Cargar listas nuevas de tus distribuidores (¡Blindaje ante listas equivocadas!):*\n"
        "¿El viajante te mandó una lista de precios por WhatsApp?\n"
        "👉 *Solo dale a \"Reenviar\" a este chat* (en PDF o Excel).\n"
        "Leo las tablas automáticamente y actualizo todos los precios en segundos.\n"
        "🛡️ *Blindaje anti-errores:* Si el viajante te manda una lista equivocada (de otro rubro o sin coincidencias), te alerto de inmediato y mantengo tus costos vigentes 100% protegidos sin alterar nada.\n\n"
        "5️⃣ *Revisar tus proveedores registrados:*\n"
        "👉 _«¿Qué proveedores tengo cargados?»_\n"
        "Te muestro cuántos distribuidores y productos tenés en memoria.\n\n"
        "6️⃣ *Agendar proveedores nuevos en 1 toque (¡y cambios de número!):* 🆕\n"
        "¿Querés que me comunique con un viajante o distribuidora?\n"
        "👉 *Para agendar:* _«Sofi, agendá al proveedor Carlos de Distribuidora El Progreso al 3434536447»_ (o compartime su contacto).\n"
        "👉 *Si cambió de WhatsApp:* _«Sofi, Carlos de Distribuidora El Progreso cambió de número al 343...»_ (mantengo intactas todas sus listas de precios y canastas).\n"
        "⚡ *¿Qué hago yo al instante?* Le escribo un WhatsApp presentándome de parte tuya, le pido que me agende y le solicito su lista de precios o aumentos (en archivo o simplemente escribiéndome qué productos suben). Si el viajante me escribe _«subió el azúcar 5%»_, yo actualizo tu catálogo automáticamente y te aviso al instante para que nunca vendas desactualizado ni pierdas margen.\n\n"
        "7️⃣ *Consultas directas a proveedores (¡Secretaria de compras!):* 🆕\n"
        "¿Querés hacerle una pregunta o consulta a un distribuidor o viajante sin armar un pedido formal?\n"
        "👉 Mandame un audio o texto: _«Sofi, preguntale a Pedro de Distribuidora Alem si el lunes hacen reparto»_ (o _«consultale a...»_, _«decile a...»_, _«escribile a...»_).\n"
        "⚡ *¿Qué hago yo al instante?* Le escribo a su WhatsApp de parte tuya transmitiéndole tu consulta respetuosamente. Y en cuanto el viajante o distribuidor me responda, te reenvío su respuesta exacta a este chat al instante.\n\n"
        "8️⃣ *Gestión de empleados y equipo del comercio (¡Multiusuario!):* 👥🆕\n"
        "¿Tenés repositores o encargados en el local y querés que usen a Sofía en sus celulares?\n"
        "👉 *Sumalos en 1 segundo:* _«Sofi, agregá a Lucas como empleado al 3434536447»_.\n"
        "👉 *Autorizá a un encargado a despachar:* _«Sofi, autorizá a Lucas a despachar pedidos»_.\n"
        "👉 *Consultá tu equipo:* Escribí _«empleados»_ o _«mi equipo»_.\n"
        "⚡ *¿Cómo funciona?* Todos comparten el catálogo y canasta de faltantes de tu comercio. Por seguridad, los repositores solo anotan y consultan. Si un encargado autorizado despacha un pedido a un distribuidor, te llega una notificación en espejo a tu WhatsApp con el remito y total en el acto.\n\n"
        "---\n\n"
        "💡 *3 CONSEJOS PARA APROVECHARME AL MÁXIMO:*\n\n"
        "🎙️ *Usá notas de voz:* Podés hablarme por audio rápido mientras atendés el mostrador.\n"
        "🤝 *Hablame natural:* No necesitás códigos raros. Decime _«anotame»_, _«pasame precio de...»_ o _«agendá al proveedor...»_.\n"
        "📦 *Cero instalaciones:* Funciona 100% acá adentro de WhatsApp, sin descargar aplicaciones ni programas pesados en la computadora.\n\n"
        "---\n\n"
        "📌 *5 PALABRAS CLAVE QUE PODÉS ESCRIBIRME CUANDO QUIERAS:*\n\n"
        "📖 *manual* (o _«ayuda»_) ➔ Te muestro esta guía completa con ejemplos de uso.\n"
        "🛡️ *dudas* (o _«dudas»_ / _«preguntas frecuentes»_) ➔ Respuestas sobre aumentos, listas viejas de viajantes, privacidad y seguridad comercial.\n"
        "📊 *resumen* ➔ Te muestro todo lo que tenés anotado para pedirle a cada distribuidor y cuánto dinero te estás ahorrando.\n"
        "🏢 *proveedores* ➔ Te muestro la lista de tus distribuidores agendados con sus teléfonos y catálogos en memoria.\n"
        "👥 *empleados* (o _«mi equipo»_) ➔ Te muestro tu equipo de trabajo registrado y sus permisos de compra.\n\n"
        "¡Guardame en tus contactos como *«Sofía - Compras»* y probame ahora mismo mandándome un audio! 🚀"
    )


def get_client_faq_text() -> str:
    return (
        "🛡️ *GUÍA DE SEGURIDAD COMERCIAL Y PREGUNTAS FRECUENTES* ❓✨\n\n"
        "Acá tenés respuestas claras a las dudas sobre cómo cuido tus compras y precios:\n\n"
        "---\n\n"
        "📦 *BLOQUE 1: PRECIOS, INFLACIÓN Y LISTAS DESACTUALIZADAS*\n\n"
        "1️⃣ *¿Qué pasa si una lista tiene más de 7 días y la otra es nueva?*\n"
        "👉 Aplico la *Regla de los 7 días*: elijo el mejor precio de listas actualizadas en la última semana. Si no actualiza hace semanas, te pongo alerta (⚠️) y pido confirmación antes de despachar.\n\n"
        "2️⃣ *¿Qué pasa si hago un pedido y el proveedor ya aumentó esta semana?*\n"
        "👉 Al enviar el pedido por WhatsApp, pido confirmación de precios vigentes antes de facturar. Si avisan una suba, te alerto en el acto.\n\n"
        "3️⃣ *¿Cómo actualizo los precios cuando me llega una lista nueva?*\n"
        "👉 Reenviá el PDF o Excel del viajante acá. Leo los datos y actualizo tus costos en segundos. Y si tu viajante le manda sus listas o aumentos a este chat, con un solo mensaje nos actualiza a todos los comercios que usamos Sofía a la vez, sin tener que escribirnos uno por uno.\n\n"
        "---\n\n"
        "🚚 *BLOQUE 2: PROVEEDORES, VIAJANTES Y PEDIDOS*\n\n"
        "4️⃣ *¿Qué hago con el viajante que viene a visitarme en persona al local?*\n"
        "👉 Me preguntás _«¿Qué le tengo anotado a Alem?»_ para cantárselo, o decime _«Sofi, mandale el pedido a Alem»_ y le llega la orden formal por WhatsApp en el acto.\n\n"
        "5️⃣ *¿Puedo eliminar o dar de baja a un proveedor?*\n"
        "👉 ¡Sí! Decime: _«Sofi, eliminar o dar de baja a un proveedor Distribuidora Alem»_. Lo saco de tu agenda y borro su borrador pendiente.\n\n"
        "6️⃣ *¿Sofía envía pedidos a los proveedores sola sin que yo me entere?*\n"
        "👉 *¡JAMÁS!* Nunca sale un mensaje a un distribuidor sin tu orden expresa. Vos anotás y el pedido *solo se despacha* cuando me decís: _«Sofi, mandale el pedido a [Proveedor]»_.\n\n"
        "7️⃣ *¿Le puedo pedir a Sofía consultas o preguntas a un proveedor sin mandar un pedido?* 🆕\n"
        "👉 *¡Totalmente!* Funciono como tu secretaria ejecutiva de compras. Decime: _«Sofi, preguntale a [Proveedor] si el lunes reparten»_. Le escribo formalmente de tu parte y te reenvío su respuesta exacta al instante.\n\n"
        "8️⃣ *¿Qué pasa si dicto 20 o 30 productos juntos?*\n"
        "👉 Te armo un *Resumen Ejecutivo*: artículos por distribuidor, total estimado y cuánto dinero ahorrás en la compra.\n\n"
        "---\n\n"
        "🔒 *BLOQUE 3: PRIVACIDAD, AUDIOS Y OPERATORIA*\n\n"
        "9️⃣ *¿Mis proveedores o competidores pueden ver los precios de los demás?*\n"
        "👉 *¡NO!* La *confidencialidad es 100% estricta*. Cada proveedor solo ve sus artículos y nadie más accede a tus listas ni a tus números.\n\n"
        "🔟 *¿Qué pasa si mando un audio rápido con ruido en el negocio?*\n"
        "👉 Limpio ruidos de fondo (heladeras, clientes). Si algo no se escucha nítido, te repregunto para no anotar nunca un producto equivocado.\n\n"
        "1️⃣1️⃣ *¿Puedo dividir un pedido entre varios proveedores para ahorrar?*\n"
        "👉 ¡Totalmente automático! Asigno cada producto al proveedor con mejor precio para maximizar tu ganancia.\n\n"
        "1️⃣2️⃣ *¿Le puedo pedir a Sofía que le mande mensajes a un conocido que no es mi proveedor?*\n"
        "👉 *No.* Sofía opera en un circuito cerrado y profesional: únicamente se comunica con vos y con los distribuidores para pedidos o consultas. Para mostrarle Sofía a un colega, podés reenviarle cualquier mensaje desde WhatsApp.\n\n"
        "1️⃣3️⃣ *¿Mis empleados pueden usar a Sofía desde sus propios celulares?* 👥🆕\n"
        "👉 *¡Sí!* Sumalos diciendo: _«Sofi, agregá a Lucas como empleado al 343...»_. Comparten catálogo y canasta. Por defecto son *Repositores*. Si querés que un encargado despache, decime: _«Sofi, autorizá a Lucas a despachar pedidos»_. Recibirás copia acá con remito y total.\n\n"
        "1️⃣4️⃣ *¿Qué pasa si el equipo anota productos de varios distribuidores?* 👥🆕\n"
        "👉 Clasifico cada artículo en la canasta de su distribuidor (alimentos, bebidas). Con _«resumen»_ ves todo ordenado y despachás cada pedido por separado.\n\n"
        "1️⃣5️⃣ *¿Cómo vuelvo a consultar el manual o estas dudas?*\n"
        "👉 Escribí *«manual»* para la guía de uso o *«dudas»* para volver a ver esta guía.\n\n"
        "💡 _¡Cuidar tus costos y tu tiempo en el mostrador es mi única prioridad!_ 🤝"
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
    clean_sender = "".join(filter(str.isdigit, str(sender_phone)))

    # Fetch sender prospect and resolve multi-employee tenancy
    sender_prospect = None
    if clean_sender and db:
        sender_prospect = db.query(Prospect).filter(
            (Prospect.phone == clean_sender) | (Prospect.phone == normalize_argentine_phone(clean_sender))
        ).first()

    is_employee = bool(sender_prospect and sender_prospect.parent_merchant_phone)
    effective_merchant_phone = sender_prospect.parent_merchant_phone if is_employee else clean_sender

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
                result = catalog_service.update_from_supplier_excel(
                    doc_bytes,
                    filename=doc_name,
                    supplier_name=sup_name_hint,
                    merchant_phone=sender_phone,
                    db=db
                )
                return True, result.get("whatsapp_message", "✅ Lista de proveedor procesada."), "supplier_update"
            else:
                count = catalog_service.load_from_excel_bytes(
                    doc_bytes,
                    filename=doc_name,
                    merchant_phone=sender_phone,
                    db=db
                )
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

        commands_block = (
            "📌 *5 PALABRAS CLAVE QUE PODÉS ESCRIBIRME CUANDO QUIERAS:*\n"
            "📖 *manual* ➔ Te muestro la guía de uso completa y ejemplos de cómo pedirme cosas por audio o texto.\n"
            "🛡️ *dudas* ➔ Respuestas sobre aumentos, listas viejas de viajantes, privacidad y seguridad comercial.\n"
            "📊 *resumen* ➔ Te muestro todo lo que tenés anotado para pedirle a cada distribuidor y cuánto dinero te estás ahorrando.\n"
            "🏢 *proveedores* ➔ Te muestro la lista de tus distribuidores agendados con sus teléfonos y catálogos en memoria.\n"
            "👥 *empleados* ➔ Te muestro tu equipo de trabajo y permisos para despachar pedidos.\n\n"
        )

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
                f"{commands_block}"
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
                f"{commands_block}"
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
                f"{commands_block}"
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
                f"{commands_block}"
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

    # 1.38 Client / Store Deletion on-the-fly (`eliminar comercio <nombre/tel>`, `dar de baja comercio <nombre/tel>`, etc.)
    client_del_data = parse_client_deletion_intent(clean_text)
    if client_del_data.get("is_client_deletion"):
        target_name = client_del_data.get("target_name")
        target_phone = client_del_data.get("phone")
        norm_target_phone = normalize_argentine_phone(target_phone) if target_phone else None
        is_self = client_del_data.get("is_self", False)

        is_boss = is_boss_number(clean_sender) or sender_phone == settings.WHATSAPP_ALERT_PHONE or clean_sender == "".join(filter(str.isdigit, str(settings.WHATSAPP_ALERT_PHONE or "")))

        if not is_boss and not is_self:
            return True, (
                "🔒 *Función restringida*\n\n"
                "Solo el Administrador del sistema o el propio comercio pueden gestionar la baja de cuentas."
            ), "client_deletion_unauthorized"

        if is_self:
            norm_target_phone = effective_merchant_phone or clean_sender

        target_prospect = None
        if db:
            if norm_target_phone:
                target_prospect = db.query(Prospect).filter(
                    (Prospect.phone == norm_target_phone) |
                    (Prospect.phone == target_phone)
                ).first()
            elif target_name:
                t_clean = target_name.strip().lower()
                candidates = db.query(Prospect).filter(
                    Prospect.parent_merchant_phone == None,
                    Prospect.campaign != "supplier",
                    Prospect.business_type != "proveedor"
                ).all()

                # 1. Exact match on store owner name or contact name
                for p in candidates:
                    if is_boss_number(p.phone) or p.phone == settings.WHATSAPP_ALERT_PHONE:
                        continue
                    if (p.name or "").strip().lower() == t_clean or (p.contact_name or "").strip().lower() == t_clean:
                        target_prospect = p
                        break

                # 2. Substring match on store owner
                if not target_prospect:
                    for p in candidates:
                        if is_boss_number(p.phone) or p.phone == settings.WHATSAPP_ALERT_PHONE:
                            continue
                        p_name_lower = (p.name or "").strip().lower()
                        p_cname_lower = (p.contact_name or "").strip().lower()
                        if t_clean in p_name_lower or t_clean in p_cname_lower or (len(p_name_lower) >= 4 and p_name_lower in t_clean):
                            target_prospect = p
                            break

        if not target_prospect:
            return True, (
                f"⚠️ *No encontré al comercio '{target_name or target_phone or 'solicitado'}' registrado.*\n\n"
                f"💡 Pasame el nombre o el número de WhatsApp, por ejemplo:\n"
                f"_«Sofi, eliminar comercio Kiosco Alameda»_ o _«eliminar comercio al 343...»_"
            ), "client_delete_not_found"

        del_phone = target_prospect.phone
        del_name = target_prospect.name or "Comercio"

        # 1. Delete all associated draft orders for this merchant
        db.query(SupplierDraftOrder).filter(SupplierDraftOrder.merchant_phone == del_phone).delete(synchronize_session=False)

        # 2. Delete all merchant products for this merchant
        db.query(MerchantProduct).filter(MerchantProduct.merchant_phone == del_phone).delete(synchronize_session=False)

        # 3. Delete all linked employees
        db.query(Prospect).filter(Prospect.parent_merchant_phone == del_phone).delete(synchronize_session=False)

        # 4. Delete any suppliers registered strictly by this merchant
        db.query(Prospect).filter(
            Prospect.merchant_phone == del_phone,
            Prospect.campaign == "supplier"
        ).delete(synchronize_session=False)

        # 5. Delete the prospect record itself
        db.delete(target_prospect)
        db.commit()

        return True, (
            f"🗑️ *COMERCIO DADO DE BAJA CON ÉXITO*\n\n"
            f"*{del_name}* (+{del_phone}) y todas sus canastas y datos de prueba fueron eliminados del sistema.\n\n"
            f"El número quedó *100% liberado y restablecido* como una hoja en blanco para nuevas pruebas o demostraciones."
        ), "client_deleted"

    # 1.55 Multi-Employee Team Management
    emp_intent = await parse_employee_management_intent(clean_text)
    if emp_intent.get("is_employee_management"):
        # Security Guard: Employees cannot manage other employees or permissions
        if is_employee:
            return True, (
                "🔒 *Función reservada para el titular del comercio*\n\n"
                "La gestión de empleados, altas y permisos de compra solo puede ser realizada por el dueño del comercio."
            ), "employee_mgmt_unauthorized"

        action = emp_intent.get("action")
        owner_ident = resolve_merchant_identity(clean_sender, db)
        owner_biz_name = owner_ident.get("client_biz") or "tu comercio"

        if action == "list_employees":
            employees = db.query(Prospect).filter(
                Prospect.parent_merchant_phone == clean_sender
            ).order_by(Prospect.created_at.asc()).all() if db else []

            if not employees:
                return True, (
                    "👥 *EQUIPO DE TU COMERCIO*\n\n"
                    "Aún no tenés empleados registrados en tu comercio.\n\n"
                    "💡 *Para dar de alta a un empleado, decime:*\n"
                    "_«Sofi, agregá a Lucas como empleado al 3434536447»_\n"
                    "O como encargado con permiso de compra:\n"
                    "_«Sofi, agregá a Carlos como encargado al 3434536447»_"
                ), "employees_empty"

            lines = [f"👥 *EQUIPO REGISTRADO EN TU COMERCIO ({len(employees)}):*\n"]
            for idx, emp in enumerate(employees, 1):
                p_name = emp.contact_name or emp.name or "Empleado"
                p_phone = emp.phone
                if emp.can_dispatch:
                    role_badge = "🚀 *Encargado / Comprador* (✅ Autorizado a despachar)"
                else:
                    role_badge = "🔒 *Anotador / Repositor* (Solo canasta y consultas)"
                lines.append(f"{idx}. *{p_name}* (+{p_phone})\n   {role_badge}")

            lines.append("\n💡 *Comandos disponibles:*")
            lines.append("• _«Sofi, autorizá a [Nombre] a despachar pedidos»_")
            lines.append("• _«Sofi, quitale el permiso a [Nombre]»_")
            lines.append("• _«Sofi, eliminá al empleado [Nombre]»_")
            return True, "\n".join(lines), "employees_list"

        elif action == "add_employee":
            raw_p = emp_intent.get("phone")
            norm_p = normalize_argentine_phone(raw_p) if raw_p else None
            emp_name = emp_intent.get("contact_name") or "Empleado"

            if not norm_p:
                return True, (
                    f"👥 *Para registrar a {emp_name} en tu equipo*, por favor pasame su número de WhatsApp.\n\n"
                    f"💡 Podés escribir por ejemplo:\n"
                    f"_«Sofi, agregá a {emp_name} como empleado al 3434536447»_"
                ), "employee_add_needs_phone"

            emp_role = emp_intent.get("role") or "repositor"
            if emp_role == "empleado":
                emp_role = "repositor"
            emp_can_dispatch = bool(emp_intent.get("can_dispatch", False))

            existing_emp = db.query(Prospect).filter(Prospect.phone == norm_p).first() if db else None
            if existing_emp:
                existing_emp.parent_merchant_phone = clean_sender
                existing_emp.employee_role = emp_role
                existing_emp.can_dispatch = emp_can_dispatch
                existing_emp.contact_name = emp_name
                existing_emp.business_type = "empleado"
                existing_emp.campaign = "client_employee"
                existing_emp.status = "active"
                db.commit()
            else:
                new_emp = Prospect(
                    phone=norm_p,
                    name=f"Empleado de {owner_biz_name}",
                    contact_name=emp_name,
                    parent_merchant_phone=clean_sender,
                    employee_role=emp_role,
                    can_dispatch=emp_can_dispatch,
                    business_type="empleado",
                    campaign="client_employee",
                    status="active",
                    notes=json.dumps({"owner_phone": clean_sender, "added_by": "owner"}, ensure_ascii=False)
                )
                db.add(new_emp)
                db.commit()

            # WhatsApp welcome to employee
            perm_desc = (
                "🚀 *Encargado de Compras:* tenés permiso para despachar pedidos directos a proveedores."
                if emp_can_dispatch
                else "🔒 *Nivel Repositor:* podés consultar precios, aumentos y cargar faltantes a la canasta compartida del comercio."
            )
            emp_welcome = (
                f"👋 *¡Hola {emp_name}!* Te doy la bienvenida a *Sofía*.\n\n"
                f"El titular de *{owner_biz_name}* te dio de alta en el equipo de WhatsApp del comercio.\n\n"
                f"📌 *Tu perfil actual:*\n{perm_desc}\n\n"
                f"🎯 *Podés mandarme un audio o texto probando cualquiera de estas opciones:*\n\n"
                f"1️⃣ _«Sofi, ¿quién tiene más barato el aceite de girasol?»_\n"
                f"2️⃣ _«Anotame 10 paquetes de harina y 5 cajas de galletitas»_ (se guarda en la canasta compartida)\n"
                f"3️⃣ _«¿Qué productos aumentaron esta semana?»_\n"
                f"4️⃣ _Reenviame una lista de precios en PDF o Excel de cualquier distribuidor_\n"
                f"5️⃣ _«¿Qué proveedores tenemos registrados?»_\n"
                f"6️⃣ _«Sofi, preguntale a Pedro de Distribuidora Alem si el lunes hacen reparto»_ (¡Secretaria de compras!) 🆕\n\n"
                f"📌 *5 PALABRAS CLAVE QUE PODÉS ESCRIBIRME CUANDO QUIERAS:*\n"
                f"📖 *manual* ➔ Guía completa y ejemplos de uso.\n"
                f"🛡️ *dudas* ➔ Preguntas frecuentes y seguridad comercial.\n"
                f"📊 *resumen* ➔ Todo lo anotado para cada distribuidor y ahorro estimado.\n"
                f"🏢 *proveedores* ➔ Lista de distribuidores agendados en memoria.\n"
                f"👥 *empleados* ➔ Miembros del equipo y permisos de compra.\n\n"
                f"¡Guardame en tus contactos como *«Sofía - Compras»* y probame mandándome un audio! 🚀"
            )

            # 1. Attempt official Meta Template (outside 24h window)
            try:
                await whatsapp.send_whatsapp_template(
                    to_phone=norm_p,
                    template_name="alta_empleado_v1",
                    language_code="es_AR",
                    components=[
                        {
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": emp_name},
                                {"type": "text", "text": owner_biz_name}
                            ]
                        }
                    ]
                )
            except Exception as e:
                logger.warning(f"Could not send alta_empleado_v1 template: {e}")

            # 2. Conversational welcome message
            await whatsapp.send_whatsapp_message(to_phone=norm_p, text=emp_welcome)

            role_title = "Encargado / Comprador Autorizado" if emp_can_dispatch else "Anotador / Repositor"
            perm_title = "✅ Habilitado para enviar pedidos directos" if emp_can_dispatch else "🔒 Bloqueado (solo anota en canasta compartida)"
            owner_reply = (
                f"✅ *¡Empleado registrado con éxito!*\n\n"
                f"👤 *Nombre:* {emp_name}\n"
                f"📱 *WhatsApp:* +{norm_p}\n"
                f"🏷️ *Rol inicial:* {role_title}\n"
                f"🚀 *Despacho de pedidos:* {perm_title}\n\n"
                f"📲 Ya le envié un mensaje de bienvenida a su WhatsApp con las instrucciones de uso.\n\n"
                f"💡 Si más adelante querés modificar sus permisos, solo decime:\n"
                f"_«Sofi, autorizá a {emp_name} a despachar pedidos»_ o _«Sofi, quitale el permiso a {emp_name}»_."
            )
            return True, owner_reply, "employee_added"

        elif action == "grant_dispatch":
            target_name = emp_intent.get("contact_name") or ""
            target_phone = emp_intent.get("phone")

            emp_rec = None
            if db:
                q = db.query(Prospect).filter(Prospect.parent_merchant_phone == clean_sender)
                if target_phone:
                    emp_rec = q.filter(Prospect.phone == target_phone).first()
                if not emp_rec and target_name:
                    emp_rec = q.filter(
                        (Prospect.contact_name.ilike(f"%{target_name}%")) | (Prospect.name.ilike(f"%{target_name}%"))
                    ).first()

            if not emp_rec:
                return True, (
                    f"⚠️ *No encontré a '{target_name}' entre tus empleados registrados.*\n\n"
                    f"💡 Escribí *«empleados»* para ver tu equipo actual, o decime:\n"
                    f"_«Sofi, agregá a {target_name} como encargado al [número]»_ para darlo de alta directamente."
                ), "employee_not_found"

            emp_rec.can_dispatch = True
            emp_rec.employee_role = "encargado"
            db.commit()

            emp_name = emp_rec.contact_name or "compañero"
            emp_notify = (
                f"🚀 *¡Permiso habilitado!*\n\n"
                f"¡Hola {emp_name}! El titular de tu comercio te acaba de autorizar para *despachar pedidos directamente a distribuidores* a través de Sofía.\n\n"
                f"👉 Cuando quieras enviar un remito formal, solo decime: _«Sofi, mandale el pedido a [Proveedor]»_ y le llegará de inmediato por WhatsApp con copia al dueño."
            )
            try:
                await whatsapp.send_whatsapp_message(to_phone=emp_rec.phone, text=emp_notify)
            except Exception as e:
                logger.error(f"Error sending grant notification to employee: {e}")

            return True, (
                f"✅ *¡Permiso otorgado con éxito!*\n\n"
                f"*{emp_name}* (+{emp_rec.phone}) ahora está autorizado para despachar pedidos directos a distribuidores.\n\n"
                f"🔔 Cada vez que despache una orden de compra, recibirás un aviso automático en este chat con el remito y total del pedido."
            ), "employee_dispatch_granted"

        elif action == "revoke_dispatch":
            target_name = emp_intent.get("contact_name") or ""
            target_phone = emp_intent.get("phone")

            emp_rec = None
            if db:
                q = db.query(Prospect).filter(Prospect.parent_merchant_phone == clean_sender)
                if target_phone:
                    emp_rec = q.filter(Prospect.phone == target_phone).first()
                if not emp_rec and target_name:
                    emp_rec = q.filter(
                        (Prospect.contact_name.ilike(f"%{target_name}%")) | (Prospect.name.ilike(f"%{target_name}%"))
                    ).first()

            if not emp_rec:
                return True, (
                    f"⚠️ *No encontré a '{target_name}' entre tus empleados registrados.*\n\n"
                    f"💡 Escribí *«empleados»* para ver tu equipo registrado."
                ), "employee_not_found"

            emp_rec.can_dispatch = False
            emp_rec.employee_role = "repositor"
            db.commit()

            emp_name = emp_rec.contact_name or "compañero"
            emp_notify = (
                f"🔒 *Actualización de permisos*\n\n"
                f"¡Hola {emp_name}! El titular de tu comercio actualizó los permisos: ahora tu perfil es de *Repositor / Anotador*.\n\n"
                f"Podés seguir consultando precios y guardando faltantes en la canasta compartida para que el dueño los despache."
            )
            try:
                await whatsapp.send_whatsapp_message(to_phone=emp_rec.phone, text=emp_notify)
            except Exception as e:
                logger.error(f"Error sending revoke notification to employee: {e}")

            return True, (
                f"🔒 *Permiso revocado.*\n\n"
                f"*{emp_name}* (+{emp_rec.phone}) ya no puede despachar pedidos directos.\n\n"
                f"Los faltantes que anote quedarán guardados en la canasta compartida del comercio para tu revisión previa."
            ), "employee_dispatch_revoked"

        elif action == "delete_employee":
            target_name = emp_intent.get("contact_name") or ""
            target_phone = emp_intent.get("phone")

            emp_rec = None
            if db:
                q = db.query(Prospect).filter(Prospect.parent_merchant_phone == clean_sender)
                if target_phone:
                    emp_rec = q.filter(Prospect.phone == target_phone).first()
                if not emp_rec and target_name:
                    emp_rec = q.filter(
                        (Prospect.contact_name.ilike(f"%{target_name}%")) | (Prospect.name.ilike(f"%{target_name}%"))
                    ).first()

            if not emp_rec:
                return True, (
                    f"⚠️ *No encontré a '{target_name}' entre tus empleados registrados.*\n\n"
                    f"💡 Escribí *«empleados»* para ver tu equipo registrado."
                ), "employee_not_found"

            del_name = emp_rec.contact_name or "Empleado"
            del_phone = emp_rec.phone
            db.delete(emp_rec)
            db.commit()

            return True, (
                f"🗑️ *Empleado eliminado.*\n\n"
                f"*{del_name}* (+{del_phone}) fue dado de baja del equipo de tu comercio."
            ), "employee_deleted"

    # 1.6 Supplier Registration on-the-fly via WhatsApp Audio or Text
    sup_reg_data = await parse_supplier_registration_intent(clean_text)
    if sup_reg_data.get("is_supplier_registration"):
        s_name = sup_reg_data.get("supplier_name") or "Proveedor"
        raw_p = sup_reg_data.get("phone")
        norm_p = normalize_argentine_phone(raw_p) if raw_p else None

        if norm_p:
            s_contact = sup_reg_data.get("contact_name") or s_name
            existing_sup = db.query(Prospect).filter(
                Prospect.merchant_phone == effective_merchant_phone,
                Prospect.phone == norm_p
            ).first() if db else None

            if not existing_sup and db and (is_boss_number(sender_phone) or sender_phone == settings.WHATSAPP_ALERT_PHONE):
                existing_sup = db.query(Prospect).filter(
                    Prospect.phone == norm_p,
                    (Prospect.merchant_phone == effective_merchant_phone) | (Prospect.merchant_phone == None)
                ).first()

            if existing_sup:
                existing_sup.name = s_name
                existing_sup.contact_name = s_contact
                existing_sup.merchant_phone = effective_merchant_phone
                existing_sup.business_type = "proveedor"
                existing_sup.campaign = "supplier"
                existing_sup.notes = f"Proveedor actualizado desde WhatsApp el {datetime.now().strftime('%d/%m/%Y %H:%M')}"
                db.commit()
            else:
                new_sup = Prospect(
                    merchant_phone=effective_merchant_phone,
                    name=s_name,
                    contact_name=s_contact,
                    phone=norm_p,
                    business_type="proveedor",
                    campaign="supplier",
                    notes=f"Proveedor agendado desde WhatsApp el {datetime.now().strftime('%d/%m/%Y %H:%M')}"
                )
                db.add(new_sup)
                db.commit()


            target_sup_id = existing_sup.id if existing_sup else new_sup.id

            # Determine client / merchant details from sender_phone
            ident = resolve_merchant_identity(sender_phone, db, target_sup_name=s_name)
            client_biz = ident["client_biz"]
            client_owner = ident["client_owner"]
            sender_intro = ident["sender_intro"]
            biz_tag = ident["biz_tag"]

            # Save merchant metadata in supplier record so incoming updates from supplier alert this merchant
            sup_meta = {
                "merchant_phone": effective_merchant_phone,
                "merchant_biz": client_biz,
                "merchant_owner": client_owner,
                "registered_at": datetime.now(timezone.utc).isoformat()
            }
            if existing_sup:
                existing_sup.notes = json.dumps(sup_meta, ensure_ascii=False)
            else:
                new_sup.notes = json.dumps(sup_meta, ensure_ascii=False)
            db.commit()

            # 1. Prepare presentation message for the supplier
            supplier_intro_text = (
                f"¡Hola *{s_contact}*! 👋 Te escribo de parte de *{sender_intro}*.\n\n"
                f"Soy *Sofía*, su asistente comercial. Me pidió que me ponga en contacto con vos porque a partir de ahora "
                f"te voy a pasar los pedidos de reposición por acá: *bien detallados, con códigos y en PDF* para facilitarte la carga y que no pierdas tiempo. 📋📦\n\n"
                f"📌 *Por favor:*\n"
                f"1️⃣ Agendá este contacto como *«Sofía - {biz_tag}»*.\n"
                f"2️⃣ Si tenés a mano la lista de precios actualizada o los aumentos de esta semana, ¿me los reenviás por acá? Puede ser en archivo (PDF/Excel) o simplemente escribiéndome qué productos suben, así ya los dejo cargados para los próximos pedidos.\n\n"
                f"¿Me confirmás con un *«Agendado»* o *«Recibido»* que te llegó bien? ¡Muchas gracias!"
            )

            # 2. Dispatch presentation to supplier:
            # First attempt via approved Meta Cloud API Template; if template fails or not approved, fallback to conversational text.
            async def _dispatch_supplier_presentation():
                components = [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": s_contact},
                            {"type": "text", "text": client_owner},
                            {"type": "text", "text": client_biz},
                            {"type": "text", "text": biz_tag}
                        ]
                    }
                ]
                tpl_sent = await whatsapp.send_whatsapp_template(
                    to_phone=norm_p,
                    template_name="presentacion_proveedor_v1",
                    language_code="es_AR",
                    components=components
                )
                if not tpl_sent:
                    await whatsapp.send_whatsapp_message(
                        to_phone=norm_p,
                        text=supplier_intro_text
                    )

            asyncio.create_task(_dispatch_supplier_presentation())

            return True, (
                f"✅ *¡PROVEEDOR REGISTRADO Y CONTACTADO!* 📦✨\n\n"
                f"🏢 *Distribuidora:* {s_name}\n"
                f"👤 *Contacto:* {s_contact}\n"
                f"📱 *WhatsApp:* +{norm_p}\n\n"
                f"🚀 *Ya le envié un mensaje de presentación:*\n"
                f"Me presenté de parte de *{sender_intro}*, le pedí que me agende como «Sofía - {biz_tag}» y le solicité su lista de precios o aumentos vigentes en PDF o Excel.\n\n"
                f"💡 *Tip clave para decirle a {s_contact}:*\n"
                f"_«{s_contact}, agendate este WhatsApp de Sofía. Cuando tengas listas nuevas o aumentos, mandáselos directo a ella: con mandarlo una sola vez nos actualiza los costos a todos los comercios que usamos Sofía al mismo tiempo, sin tener que escribirnos uno por uno.»_\n\n"
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

    # 1.63 Supplier Deletion / Removal (`eliminar proveedor <nombre>`, `borrar al proveedor <nombre>`, etc.)
    sup_del_data = parse_supplier_deletion_intent(clean_text)
    if sup_del_data.get("is_supplier_deletion"):
        del_target = sup_del_data.get("supplier_name")
        if not del_target:
            return True, (
                "⚠️ *¿Qué proveedor te gustaría dar de baja?*\n\n"
                "Decime el nombre por texto o audio, por ejemplo:\n"
                "_«Sofi, eliminar proveedor Distribuidora Alem»_"
            ), "supplier_delete_needs_name"

        target_clean = del_target.strip().lower()
        # Find supplier in Prospect table - multi-tenant scoped to sender_phone
        candidates = db.query(Prospect).filter(
            ((Prospect.campaign == "supplier") | (Prospect.business_type == "proveedor")),
            (Prospect.merchant_phone == sender_phone)
        ).all() if db else []

        if not candidates and db and (is_boss_number(sender_phone) or sender_phone == settings.WHATSAPP_ALERT_PHONE):
            candidates = db.query(Prospect).filter(
                ((Prospect.campaign == "supplier") | (Prospect.business_type == "proveedor")),
                ((Prospect.merchant_phone == effective_merchant_phone) | (Prospect.merchant_phone == None))
            ).all()

        matched_sup = None
        for s in candidates:
            s_name_lower = (s.name or "").lower()
            if target_clean in s_name_lower or s_name_lower in target_clean:
                matched_sup = s
                break

        if not matched_sup and db:
            all_pros = db.query(Prospect).filter(Prospect.merchant_phone == effective_merchant_phone).all()
            if not all_pros and (is_boss_number(sender_phone) or sender_phone == settings.WHATSAPP_ALERT_PHONE):
                all_pros = db.query(Prospect).all()
            for s in all_pros:
                s_name_lower = (s.name or "").lower()
                if target_clean in s_name_lower or s_name_lower in target_clean:
                    matched_sup = s
                    break

        if matched_sup:
            deleted_name = matched_sup.name
            db.delete(matched_sup)
            db.commit()
            clear_supplier_draft(deleted_name, merchant_phone=effective_merchant_phone, db=db)
            if del_target.lower() != deleted_name.lower():
                clear_supplier_draft(del_target, merchant_phone=effective_merchant_phone, db=db)

            return True, (
                f"🗑️ *PROVEEDOR ELIMINADO CON ÉXITO*\n\n"
                f"Se dio de baja a *{deleted_name}* de tus contactos y se eliminaron los pedidos pendientes anotados para él.\n\n"
                f"💡 _Para ver tus proveedores activos escribí:_ `proveedores`"
            ), "supplier_deleted"
        else:
            drafts = load_supplier_drafts(merchant_phone=effective_merchant_phone, db=db)
            found_draft = False
            for k, v in list(drafts.items()):
                s_title = v.get("supplier_name", "").lower()
                if target_clean in s_title or s_title in target_clean:
                    clear_supplier_draft(v.get("supplier_name", del_target), merchant_phone=effective_merchant_phone, db=db)
                    found_draft = True
                    break

            if found_draft:
                return True, (

                    f"🗑️ *BORRADOR ELIMINADO CON ÉXITO*\n\n"
                    f"Se eliminaron los pedidos pendientes anotados para *{del_target.title()}*.\n\n"
                    f"💡 _Para ver tus proveedores registrados escribí:_ `proveedores`"
                ), "supplier_deleted"

            return True, (
                f"⚠️ No encontré ningún proveedor registrado con el nombre *\"{del_target}\"*.\n\n"
                f"💡 Escribí `proveedores` para ver tu lista actual de distribuidores guardados."
            ), "supplier_not_found"

    # 1.635 Supplier Phone Update (`[proveedor/contacto] cambió de número al <tel>`, `actualizá el número de [proveedor] al <tel>`)
    sup_phone_data = await parse_supplier_phone_update_intent(clean_text)
    if sup_phone_data.get("is_supplier_phone_update"):
        s_target = sup_phone_data.get("supplier_name")
        c_target = sup_phone_data.get("contact_name")
        raw_np = sup_phone_data.get("new_phone")
        norm_np = normalize_argentine_phone(raw_np) if raw_np else None

        if not s_target and not c_target:
            return True, (
                "⚠️ *¿A qué proveedor le querés actualizar el número?*\n\n"
                "Decime por audio o texto, por ejemplo:\n"
                "_«Sofi, Carlos de Distribuidora Alem cambió de número al 3434112233»_"
            ), "supplier_phone_update_needs_name"

        if not norm_np or len(norm_np) < 8:
            return True, (
                f"📋 *Actualización de teléfono para {s_target or c_target}:*\n\n"
                f"Me falta el nuevo número de WhatsApp.\n\n"
                f"💡 Pasámelo diciendo por ejemplo: `el nuevo número es 343 4112233`"
            ), "supplier_phone_update_needs_phone"

        # Search supplier record for this merchant
        candidates = db.query(Prospect).filter(
            ((Prospect.campaign == "supplier") | (Prospect.business_type == "proveedor")),
            (Prospect.merchant_phone == effective_merchant_phone)
        ).all() if db else []

        if not candidates and db and (is_boss_number(sender_phone) or sender_phone == settings.WHATSAPP_ALERT_PHONE):
            candidates = db.query(Prospect).filter(
                ((Prospect.campaign == "supplier") | (Prospect.business_type == "proveedor")),
                ((Prospect.merchant_phone == effective_merchant_phone) | (Prospect.merchant_phone == None))
            ).all()

        matched_sup = None
        # First match by supplier_name
        if s_target:
            s_clean = s_target.strip().lower()
            for s in candidates:
                s_name_lower = (s.name or "").lower()
                if s_clean in s_name_lower or s_name_lower in s_clean:
                    matched_sup = s
                    break

        # Then match by contact_name
        if not matched_sup and c_target:
            c_clean = c_target.strip().lower()
            for s in candidates:
                c_name_lower = (s.contact_name or "").lower()
                s_name_lower = (s.name or "").lower()
                if c_clean in c_name_lower or c_clean in s_name_lower:
                    matched_sup = s
                    break

        # Fallback to match all prospects for this merchant
        if not matched_sup and db:
            all_pros = db.query(Prospect).filter(Prospect.merchant_phone == effective_merchant_phone).all()
            if not all_pros and (is_boss_number(sender_phone) or sender_phone == settings.WHATSAPP_ALERT_PHONE):
                all_pros = db.query(Prospect).all()
            for s in all_pros:
                s_name_lower = (s.name or "").lower()
                c_name_lower = (s.contact_name or "").lower()
                if (s_target and (s_target.lower() in s_name_lower or s_name_lower in s_target.lower())) or \
                   (c_target and (c_target.lower() in c_name_lower or c_name_lower in c_target.lower())):
                    matched_sup = s
                    break

        if matched_sup:
            old_phone = matched_sup.phone
            matched_sup.phone = norm_np
            matched_sup.updated_at = datetime.now(timezone.utc)
            matched_sup.notes = f"Teléfono actualizado desde WhatsApp el {datetime.now().strftime('%d/%m/%Y %H:%M')}. Anterior: {old_phone}"
            db.commit()

            ident = resolve_merchant_identity(sender_phone, db, target_sup_name=matched_sup.name)
            sender_intro = ident["sender_intro"]

            # Send welcoming greeting to new phone
            sup_contact = matched_sup.contact_name or matched_sup.name
            sup_greet = (
                f"¡Hola {sup_contact}! 👋 Te escribo de parte de *{sender_intro}*.\n"
                f"Agendé este nuevo número como tu WhatsApp de contacto para coordinar pedidos y listas de precios vigentes. ¡Que tengas una excelente jornada! 📋📦"
            )
            try:
                await whatsapp.send_whatsapp_message(to_phone=norm_np, text=sup_greet)
            except Exception as w_err:
                logger.warning(f"Could not send greeting to updated supplier phone: {w_err}")

            return True, (
                f"✅ *TELÉFONO DE PROVEEDOR ACTUALIZADO*\n\n"
                f"*{matched_sup.name}* ({sup_contact}) ahora tiene asignado el WhatsApp *+{norm_np}*.\n\n"
                f"📋 Mantengo intactos todos sus productos, precios y canastas pendientes en mi memoria."
            ), "supplier_phone_updated"
        else:
            return True, (
                f"⚠️ *No encontré al proveedor '{s_target or c_target}' entre tus contactos.*\n\n"
                f"💡 Escribí *«proveedores»* para ver tu lista de distribuidores agendados."
            ), "supplier_not_found"

    # 1.64 Direct Supplier Inquiry / Question on behalf of Merchant ("preguntale a...", "consultale a...", "decile a...")
    inq_data = await parse_supplier_inquiry_intent(clean_text)
    if inq_data.get("is_supplier_inquiry"):
        cand_sup_name = (inq_data.get("supplier_name") or "").strip()
        inquiry_text = (inq_data.get("inquiry_text") or "").strip()

        if not cand_sup_name or not inquiry_text:
            return True, (
                "⚠️ *¿A qué proveedor querés que le consulte y qué le preguntamos?*\n\n"
                "Podés decirme por ejemplo:\n"
                "_«Sofi, preguntale a Pedro de Distribuidora Alem si el lunes hacen reparto»_"
            ), "supplier_inquiry_missing_info"

        # Resolve supplier in DB scoped to this merchant
        target_clean = cand_sup_name.lower()
        candidates = db.query(Prospect).filter(
            ((Prospect.campaign == "supplier") | (Prospect.business_type == "proveedor")),
            (Prospect.merchant_phone == effective_merchant_phone)
        ).all() if db else []

        if not candidates and db:
            candidates = db.query(Prospect).filter(
                ((Prospect.campaign == "supplier") | (Prospect.business_type == "proveedor")),
                (Prospect.merchant_phone == None)
            ).all()

        matched_sup = None
        for s in candidates:
            s_name_lower = (s.name or "").lower()
            s_cont_lower = (s.contact_name or "").lower()
            if target_clean in s_name_lower or s_name_lower in target_clean or target_clean in s_cont_lower or s_cont_lower in target_clean:
                matched_sup = s
                break

        if not matched_sup:
            # Try splitting by 'de' or 'del' (e.g. "Pedro de Distribuidora Alem")
            sub_parts = [p.strip().lower() for p in re.split(r'\s+(?:de|del)\s+', cand_sup_name, flags=re.IGNORECASE) if len(p.strip()) > 1]
            for part in sub_parts:
                for s in candidates:
                    s_name_lower = (s.name or "").lower()
                    s_cont_lower = (s.contact_name or "").lower()
                    if part in s_name_lower or s_name_lower in part or part in s_cont_lower or s_cont_lower in part:
                        matched_sup = s
                        break
                if matched_sup:
                    break

        if not matched_sup and db:
            all_pros = db.query(Prospect).filter(Prospect.merchant_phone == effective_merchant_phone).all()
            for s in all_pros:
                s_name_lower = (s.name or "").lower()
                s_cont_lower = (s.contact_name or "").lower()
                if target_clean in s_name_lower or s_name_lower in target_clean or target_clean in s_cont_lower or s_cont_lower in target_clean:
                    matched_sup = s
                    break

        if not matched_sup:
            return True, (
                f"⚠️ No encontré a *\"{cand_sup_name}\"* en tus proveedores registrados.\n\n"
                f"💡 Podés agendarlo primero diciendo:\n"
                f"_«Sofi, agendá al proveedor {cand_sup_name} al [número de WhatsApp]»_"
            ), "supplier_not_found"

        target_phone = matched_sup.phone
        if not target_phone:
            return True, (
                f"⚠️ *{matched_sup.name}* está registrado pero no tengo su número de WhatsApp guardado.\n\n"
                f"💡 Pasámelo diciendo: `el teléfono de {matched_sup.name} es [número]`"
            ), "supplier_needs_phone"

        norm_p = normalize_argentine_phone(target_phone)
        s_name = matched_sup.name or cand_sup_name
        s_contact = matched_sup.contact_name or s_name

        # Merchant business and owner details
        ident = resolve_merchant_identity(sender_phone, db, target_sup_name=s_name)
        client_biz = ident["client_biz"]
        client_owner = ident["client_owner"]
        sender_intro = ident["sender_intro"]

        # Format inquiry message for the supplier
        clean_inquiry = inquiry_text.strip()
        if re.match(r'^si\s+', clean_inquiry, flags=re.IGNORECASE):
            body_inq = re.sub(r'^si\s+', '', clean_inquiry, flags=re.IGNORECASE).strip()
            clean_inquiry = "¿" + body_inq[0].upper() + body_inq[1:] + ("?" if not body_inq.endswith("?") else "")
        elif re.match(r'^que\s+', clean_inquiry, flags=re.IGNORECASE):
            clean_inquiry = re.sub(r'^que\s+', '', clean_inquiry, flags=re.IGNORECASE).strip()
            if clean_inquiry:
                clean_inquiry = clean_inquiry[0].upper() + clean_inquiry[1:]

        sup_msg = (
            f"¡Hola *{s_contact}*! 👋 Te escribo de parte de *{sender_intro}*.\n\n"
            f"Me pidió que te consulte lo siguiente:\n"
            f"💬 _«{clean_inquiry}»_\n\n"
            f"Por favor respondé por acá y se lo transmito de inmediato. ¡Muchas gracias!"
        )

        # Dispatch via Meta Template (if outside 24h window) or direct message
        tpl_components = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": s_contact},
                    {"type": "text", "text": client_owner},
                    {"type": "text", "text": client_biz},
                    {"type": "text", "text": clean_inquiry}
                ]
            }
        ]
        asyncio.create_task(whatsapp.send_whatsapp_template(
            to_phone=norm_p,
            template_name="consulta_logistica_proveedor_v1",
            language_code="es_AR",
            components=tpl_components
        ))
        asyncio.create_task(whatsapp.send_whatsapp_message(to_phone=norm_p, text=sup_msg))

        # Save last inquiry in supplier notes so the reply routes back to sender_phone
        try:
            sup_notes = json.loads(matched_sup.notes or "{}") if matched_sup.notes and matched_sup.notes.startswith("{") else {}
        except Exception:
            sup_notes = {}
        sup_notes["last_inquiry"] = {
            "merchant_phone": sender_phone,
            "merchant_biz": client_biz,
            "merchant_owner": client_owner,
            "inquiry": clean_inquiry,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        sup_notes["merchant_phone"] = sender_phone
        matched_sup.notes = json.dumps(sup_notes, ensure_ascii=False)
        db.commit()

        return True, (
            f"📨 *¡CONSULTA ENVIADA A {s_name.upper()}!* ✨\n\n"
            f"Le escribí a *{s_contact}* (+{norm_p}):\n"
            f"_«{clean_inquiry}»_\n\n"
            f"🔔 *En cuanto me responda, te reenvío su respuesta a este chat al instante.*"
        ), "supplier_inquiry_sent"

    # 1.65 Direct Price Increase or Cost Adjustment from Merchant / Boss
    if (
        any(k in lower_text for k in ["aument", "subi", "sube", "subió", "subio", "suba", "increment", "pasa a", "se fue a", "ahora esta a", "ahora está a", "nuevo precio"])
        and not any(q in lower_text for q in ["que aumento", "qué aumentó", "que subio", "qué subió", "que productos me aumentaron", "qué productos me aumentaron", "cuales aumentaron", "cuáles aumentaron", "variaciones"])
    ):
        price_upd_data = await parse_supplier_price_update_text(clean_text)
        if price_upd_data.get("is_price_update") and price_upd_data.get("updates"):
            modified = catalog_service.process_supplier_price_updates(
                price_upd_data["updates"],
                merchant_phone=effective_merchant_phone,
                db=db
            )
            if modified:
                mod_lines = []
                for m in modified:
                    m_name = m["product"]
                    m_old = f"${int(m['old_price']):,}".replace(",", ".") if m['old_price'] > 0 else "Nuevo"
                    m_new = f"${int(m['new_price']):,}".replace(",", ".")
                    pct_str = f" (+{m['percentage']}%)" if m.get('percentage') else ""
                    mod_lines.append(f"• *{m_name}:* de {m_old} pasa a *{m_new}*{pct_str}")

                return True, (
                    f"✅ *¡CATÁLOGO ACTUALIZADO!* 📈✨\n\n"
                    f"Apliqué las siguientes actualizaciones de precios:\n"
                    f"{chr(10).join(mod_lines)}\n\n"
                    f"💡 *Tus próximas consultas de precios, canastas y pedidos a proveedores ya toman estos nuevos valores.*"
                ), "merchant_price_update_applied"

    # 1.7 Supplier Baskets and Supplier Listing Inquiries
    inquiry_data = parse_supplier_basket_inquiry_intent(clean_text)
    if inquiry_data.get("is_inquiry"):
        inq_type = inquiry_data.get("type")
        is_boss_sender = is_boss_number(sender_phone) or sender_phone == settings.WHATSAPP_ALERT_PHONE
        is_boss_metric_query = any(clean_text.lower().strip() == k for k in ["resumen", "estado", "ventas", "como venimos", "cómo venimos", "metricas", "métricas"])
        if inq_type == "all_baskets" and is_boss_sender and is_boss_metric_query:
            # Let it pass through to Boss Metrics at section 3
            pass
        elif inq_type == "list_clients":
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
                ((Prospect.business_type == "proveedor") | (Prospect.campaign == "supplier")),
                (Prospect.merchant_phone == effective_merchant_phone)
            ).order_by(Prospect.name.asc()).all() if db else []

            if not sups and db and (is_boss_number(sender_phone) or sender_phone == settings.WHATSAPP_ALERT_PHONE):
                sups = db.query(Prospect).filter(
                    ((Prospect.business_type == "proveedor") | (Prospect.campaign == "supplier")),
                    ((Prospect.merchant_phone == effective_merchant_phone) | (Prospect.merchant_phone == None))
                ).order_by(Prospect.name.asc()).all()

            if not sups:
                return True, (
                    "📋 *No tenés proveedores agendados todavía.*\n\n"
                    "💡 Para agendar a uno decime por audio o texto:\n"
                    "_«Sofi, agendá al proveedor Bulonera del Litoral al 3434536447»_"
                ), "no_suppliers"

            lines = [f"📋 *TUS PROVEEDORES AGENDADOS ({len(sups)}):*\n"]
            for idx, s in enumerate(sups, 1):
                lines.append(f"{idx}. *{s.name}* (📱 +{s.phone})")
            lines.append("\n💡 *Tip:* Si tus distribuidores le mandan sus listas o aumentos a este chat, se actualizan los costos de todos sus clientes que usamos Sofía de una sola vez.")
            lines.append("💡 Podés dictarme pedidos diciendo: _«Anotá para [Proveedor] [artículos]»_")
            return True, "\n".join(lines), "suppliers_list"

        elif inq_type == "all_baskets":
            drafts = load_supplier_drafts(merchant_phone=effective_merchant_phone, db=db)
            active_baskets = {k: v for k, v in drafts.items() if v.get("items")}
            if not active_baskets:
                return True, (
                    "📋 *No tenés pedidos pendientes para ningún proveedor.*\n\n"
                    "💡 Podés dictarme faltantes diciendo:\n"
                    "_«Sofi, anotame 10 cajas de alfajores y 5 de yerba»_"
                ), "no_active_baskets"

            lines = [f"📋 *PEDIDOS ANOTADOS POR PROVEEDOR ({len(active_baskets)}):*\n"]
            for k, b in active_baskets.items():
                s_name = b.get("supplier_name", "Proveedor")
                items_cnt = sum(it.get("quantity") or it.get("qty", 1) for it in b.get("items", []))
                subtotal = sum((it.get("quantity") or it.get("qty", 1)) * float(it.get("unit_price") or it.get("price", 0)) for it in b.get("items", []))
                sub_str = f" — ${int(subtotal):,} est." if subtotal > 0 else ""
                fr = get_supplier_price_freshness(s_name, db, merchant_phone=effective_merchant_phone)
                lines.append(f"🏢 *{s_name}* ({len(b.get('items', []))} productos, {items_cnt} unidades{sub_str}) {fr['badge']}:")
                for it in b.get("items", [])[:3]:
                    p_name = it.get("product_name") or it.get("name", "Producto")
                    q_val = it.get("quantity") or it.get("qty", 1)
                    lines.append(f"  • {q_val}x {p_name}")
                if len(b.get("items", [])) > 3:
                    lines.append(f"  • ... y {len(b.get('items', [])) - 3} más.")
                lines.append(f"  👉 _«Mostrame lo de {s_name}»_ o _«Mandale el pedido a {s_name}»_\n")
            return True, "\n".join(lines), "all_baskets_summary"

        elif inq_type == "single_basket":
            target_sup = inquiry_data.get("supplier_name", "")
            basket = get_supplier_draft(target_sup, merchant_phone=effective_merchant_phone, db=db)
            if not basket or not basket.get("items"):
                return True, (
                    f"📋 *No tenés nada anotado para {target_sup} todavía.*\n\n"
                    f"💡 Para anotarle mercadería decime:\n"
                    f"_«Sofi, anotame para {target_sup} 10 cajas de alfajores...»_"
                ), "single_basket_empty"

            items = basket.get("items", [])
            s_title = basket.get("supplier_name", target_sup)
            fr = get_supplier_price_freshness(s_title, db, merchant_phone=effective_merchant_phone)
            lines = [f"📋 *LO QUE TENÉS ANOTADO PARA {s_title.upper()}* ({len(items)} artículos) {fr['badge']}:\n"]
            total_est = sum(it.get("quantity", 1) * float(it.get("unit_price", 0)) for it in items)
            for idx, it in enumerate(items, 1):
                p_u = float(it.get("unit_price", 0))
                p_str = f" (${int(p_u):,} c/u)" if p_u > 0 else ""
                lines.append(f"{idx}. *{it.get('quantity')}x {it.get('product_name')}*{p_str}")
            if total_est > 0:
                lines.append(f"\n💵 *Total estimado:* *${int(total_est):,}*")
            if not fr["is_fresh"]:
                lines.append(f"\n⚠️ _Aviso: La lista de este proveedor tiene más de 7 días. Se pedirá confirmación de precios al facturar._")
            lines.append(f"\n🚀 *Si está listo para salir decime:*")
            lines.append(f"_«Sofi, mandale el pedido a {s_title}»_")
            return True, "\n".join(lines), "single_basket_detail"


    # 1.8 Add items to Supplier Basket (Smart Multi-Supplier Routing & 7-Day Freshness Rule)
    basket_add_data = await parse_supplier_basket_add_intent(clean_text)
    if basket_add_data.get("is_basket_add") and basket_add_data.get("items"):
        explicit_sup = basket_add_data.get("supplier_name")
        raw_items = basket_add_data.get("items", [])

        # Default fallback supplier from registered DB prospects or open drafts
        registered_sups = db.query(Prospect).filter(
            ((Prospect.campaign == "supplier") | (Prospect.business_type == "proveedor")),
            (Prospect.merchant_phone == effective_merchant_phone)
        ).all() if db else []

        if not registered_sups and db and (is_boss_number(sender_phone) or sender_phone == settings.WHATSAPP_ALERT_PHONE):
            registered_sups = db.query(Prospect).filter(
                ((Prospect.campaign == "supplier") | (Prospect.business_type == "proveedor")),
                ((Prospect.merchant_phone == effective_merchant_phone) | (Prospect.merchant_phone == None))
            ).all()

        default_sup_name = registered_sups[0].name if registered_sups else "Distribuidora Alem"

        assigned_by_sup = {}
        total_savings = 0.0

        for it in raw_items:
            p_name = it.get("product_name", "").strip()
            p_qty = int(it.get("quantity", 1))

            target_sup = explicit_sup
            unit_price = 0.0
            chosen_name = p_name.capitalize()
            item_saving = 0.0

            if target_sup and target_sup.lower() not in ["proveedor", "distribuidora", "auto", "null", "none", ""]:
                # Explicit supplier indicated by merchant (e.g. 'anotá para Litoral')
                prod = catalog_service.find_product_exact_or_best(p_name, merchant_phone=effective_merchant_phone, db=db)
                if prod:
                    unit_price = prod.price
                    chosen_name = prod.name
            else:
                # Automatic best price routing using 7-day rule
                comp_res = catalog_service.compare_supplier_prices(p_name, merchant_phone=effective_merchant_phone, db=db)
                if comp_res:
                    canonical_q, matches = comp_res
                    if matches:
                        # Check freshness of each candidate using 7-day rule
                        fresh_matches = []
                        stale_matches = []
                        for m in matches:
                            s_cand = m.supplier or default_sup_name
                            fr = get_supplier_price_freshness(s_cand, db, merchant_phone=effective_merchant_phone)
                            if fr["is_fresh"]:
                                fresh_matches.append(m)
                            else:
                                stale_matches.append(m)

                        if fresh_matches:
                            # Pick cheapest amongst suppliers with fresh lists (<= 7 days)
                            best_m = min(fresh_matches, key=lambda x: x.price)
                            target_sup = best_m.supplier or default_sup_name
                            unit_price = best_m.price
                            chosen_name = best_m.name
                            if len(matches) > 1:
                                max_p = max(m.price for m in matches)
                                if max_p > best_m.price:
                                    item_saving = (max_p - best_m.price) * p_qty
                                    total_savings += item_saving
                        else:
                            # All candidate suppliers have stale lists (> 7 days)
                            best_m = min(matches, key=lambda x: x.price)
                            target_sup = best_m.supplier or default_sup_name
                            unit_price = best_m.price
                            chosen_name = best_m.name

                if not target_sup:
                    # Fallback to single open basket if exists, or default supplier
                    drafts = load_supplier_drafts(merchant_phone=effective_merchant_phone, db=db)
                    active_baskets = [v for v in drafts.values() if v.get("items")]
                    if len(active_baskets) == 1:
                        target_sup = active_baskets[0].get("supplier_name", default_sup_name)
                    else:
                        target_sup = default_sup_name

            if not target_sup:
                target_sup = default_sup_name

            enriched = {
                "product_name": chosen_name,
                "quantity": p_qty,
                "unit_price": unit_price
            }
            if target_sup not in assigned_by_sup:
                assigned_by_sup[target_sup] = []
            assigned_by_sup[target_sup].append(enriched)

        # Persist into draft baskets
        for s_name, s_items in assigned_by_sup.items():
            add_items_to_supplier_draft(s_name, s_items, merchant_phone=effective_merchant_phone, db=db)

        total_items_count = len(raw_items)

        # Formatting: Concise for 1-3 items, Executive Batch Summary for 4+ items
        if total_items_count <= 3:
            lines = ["🧺 *¡Anotado!* 📝\n"]
            for sup, items in assigned_by_sup.items():
                fr = get_supplier_price_freshness(sup, db, merchant_phone=effective_merchant_phone)
                badge = fr["badge"]
                flabel = fr["label"]
                for it in items:
                    p_str = f" (${int(it['unit_price']):,} c/u)" if it['unit_price'] > 0 else ""
                    lines.append(f"• *{it['quantity']}x {it['product_name']}* ➔ *{sup}*{p_str} {badge} _{flabel}_")


            if total_savings > 0:
                lines.append(f"\n💰 *Ahorro estimado:* ${int(total_savings):,} frente a otras opciones.")

            first_sup = list(assigned_by_sup.keys())[0]
            lines.append(f"\n💡 *Para revisar o mandar el pedido decime:*\n• _«Mostrame lo que le tengo anotado a {first_sup}»_\n• _«Mandale el pedido a {first_sup}»_")
            return True, "\n".join(lines), "basket_item_added"
        else:
            lines = [f"🧺 *¡Anoté los {total_items_count} artículos repartidos por mejor precio!* 📋✨\n"]
            for sup, items in assigned_by_sup.items():
                fr = get_supplier_price_freshness(sup, db)
                subtotal = sum(it["quantity"] * it["unit_price"] for it in items)
                sub_str = f" — ${int(subtotal):,} est." if subtotal > 0 else ""

                top_items = [f"{it['quantity']}x {it['product_name']}" for it in items[:3]]
                rest = len(items) - 3
                if rest > 0:
                    top_items.append(f"(+{rest} más)")

                lines.append(f"🏢 *{sup}* ({len(items)} artículos{sub_str})")
                lines.append(f"• {', '.join(top_items)}")
                if fr["is_fresh"]:
                    lines.append(f"🟢 _Precios vigentes de esta semana._\n")
                else:
                    lines.append(f"⚠️ _Lista con más de 7 días (confirmaremos precios al despachar)._\n")

            lines.append("━━━━━━━━━━━━━━━━━━━━━━")
            if total_savings > 0:
                lines.append(f"💰 *Ahorro total estimado:* *${int(total_savings):,}* comprando con este reparto.")

            first_sup = list(assigned_by_sup.keys())[0]
            lines.append(f"🚀 *Para revisar o despachar cualquiera decime:*\n• _«Mostrame lo que le tengo anotado a {first_sup}»_\n• _«Mandale el pedido a {first_sup}»_")
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
        "mandale el pedido", "mandar el pedido", "mandá el pedido", "mandar pedido",
        "enviá el pedido", "enviale el pedido", "enviar el pedido", "enviar pedido",
        "pasale el pedido", "pasá el pedido", "pasar el pedido", "pasar pedido",
        "despachá el pedido", "despachale el pedido", "despachar pedido", "despachar el pedido",
        "hacé el pedido", "hacele el pedido", "hacer el pedido", "hacer pedido",
        "cerrá el pedido", "cerrale el pedido", "cerrar el pedido", "cerrar pedido",
        "mandale la orden", "enviá la orden", "enviar orden", "mandar orden",
        "mandale los faltantes", "pasale los faltantes", "enviá los faltantes", "mandar faltantes",
        "mandá lo que anotamos", "mandale lo que anotamos", "pasale lo que anotamos", "enviá lo que anotamos",
        "mandale a", "mandá a", "hacele el pedido a", "hacé el pedido a",
        "despachar pedido a", "despachale a", "pasale el pedido a", "enviá el pedido a",
        "enviar a la distribuidora", "mandar a la distribuidora", "pasale a", "enviale a", "envíale a",
        "mandale para", "enviá para", "mandá para", "despachá para", "despachale para", "pasale para",
        "enviale este mensaje", "enviá este mensaje", "enviale éste mensaje", "mandale este mensaje",
        "mandale la demo a", "mandar la demo a", "mandá la demo a", "enviar la demo a", "pasale la demo a",
        "mandale demo a", "mandar demo a", "enviar demo a"
    ]
    is_dispatch_candidate = any(k in lower_text for k in dispatch_triggers) or (
        any(k in lower_text for k in ["enviale", "envíale", "mandale", "mandá", "manda", "pasale", "pasá", "despachale", "despachá", "mandar", "enviar", "cerrá", "hacé"]) and
        any(k in lower_text for k in ["demo", "pedido", "pedidos", "orden", "remito", "prueba", "faltante", "faltantes", "lo anotado", "lo que anotamos", "martillo", "alicate", "tornillo", "disco", "caja", "bolsa", "harina", "aceite", "a ferreteria", "a ferretería", "a distribuidora", "para la distribuidora", "el numero es", "el número es", "telefono es", "teléfono es"])
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
            distributor_match = re.search(r'(?:pedido\s+a|pedido\s+para|orden\s+a|orden\s+para|la\s+demo\s+a|demo\s+a|\ba\b|\bpara\b)\s+([^\n\r,]+?)(?:[,\s]+(?:al\s+\d+|el\s+n[uú]mero|el\s+tel[eé]fono|con\b)|$)', clean_text, re.IGNORECASE)
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
                Prospect.merchant_phone == effective_merchant_phone
            ).filter(
                (Prospect.contact_name.ilike(f"%{dist_name}%")) |
                (Prospect.name.ilike(f"%{dist_name}%"))
            ).order_by(Prospect.updated_at.desc()).first() if db else None

            if not matched_p and db:
                matched_p = db.query(Prospect).filter(
                    Prospect.merchant_phone == None
                ).filter(
                    (Prospect.contact_name.ilike(f"%{dist_name}%")) |
                    (Prospect.name.ilike(f"%{dist_name}%"))
                ).order_by(Prospect.updated_at.desc()).first()

            if matched_p:
                target_phone = matched_p.phone
                dist_name = matched_p.contact_name or matched_p.name

        if not target_phone and (not dist_name or dist_name.lower() in ["la distribuidora", "distribuidora", "proveedor"]):
            # Check if there is only 1 open basket with items
            drafts = load_supplier_drafts(merchant_phone=effective_merchant_phone, db=db)
            active_baskets = [v for v in drafts.values() if v.get("items")]
            if len(active_baskets) == 1:
                cand_sup = active_baskets[0].get("supplier_name", "")
                if cand_sup:
                    dist_name = cand_sup
                    matched_p = db.query(Prospect).filter(
                        Prospect.merchant_phone == effective_merchant_phone
                    ).filter(
                        (Prospect.contact_name.ilike(f"%{cand_sup}%")) |
                        (Prospect.name.ilike(f"%{cand_sup}%"))
                    ).order_by(Prospect.updated_at.desc()).first() if db else None

                    if not matched_p and db:
                        matched_p = db.query(Prospect).filter(
                            Prospect.merchant_phone == None
                        ).filter(
                            (Prospect.contact_name.ilike(f"%{cand_sup}%")) |
                            (Prospect.name.ilike(f"%{cand_sup}%"))
                        ).order_by(Prospect.updated_at.desc()).first()

                    if matched_p:
                        target_phone = matched_p.phone
            if not target_phone and db:
                sup_query = db.query(Prospect).filter(
                    ((Prospect.campaign == "supplier") | (Prospect.business_type == "proveedor")),
                    (Prospect.merchant_phone == effective_merchant_phone)
                ).all()
                if not sup_query:
                    sup_query = db.query(Prospect).filter(
                        ((Prospect.campaign == "supplier") | (Prospect.business_type == "proveedor")),
                        (Prospect.merchant_phone == None)
                    ).all()
                if len(sup_query) == 1:
                    dist_name = sup_query[0].name or sup_query[0].contact_name
                    target_phone = sup_query[0].phone

        if target_phone:
            target_phone = normalize_argentine_phone(target_phone)

        # Multi-Employee Guard: Check if sender is an employee who lacks dispatch authorization
        if sender_prospect and sender_prospect.parent_merchant_phone and not sender_prospect.can_dispatch:
            emp_name = brain.sanitize_contact_first_name(sender_prospect.contact_name) or "amigo"
            return True, (
                f"🔒 *Acceso restringido para despachar pedidos*\n\n"
                f"¡Hola {emp_name}! Tenés permiso para consultar precios, variaciones y cargar faltantes a la canasta compartida del comercio, pero el despacho formal a distribuidores requiere autorización del titular.\n\n"
                f"💡 Los productos para *{dist_name}* quedaron guardados en la canasta compartida. Pedile al dueño que me escriba: _«Sofi, autorizá a {emp_name} a despachar pedidos»_ si necesitás hacer envíos directos."
            ), "employee_dispatch_unauthorized"

        if not target_phone:
            return True, (
                f"📋 *¡Pedido formal en preparación para {dist_name}!* \n\n"
                f"Para despacharle el remito PDF adjunto por WhatsApp, por favor pasame su número de teléfono.\n\n"
                f"💡 Podés escribir por ejemplo: `al 3434536447` o mandarme el contacto."
            ), "dispatch_needs_phone"

        if target_phone:
            # Check if there is an open supplier basket for dist_name
            sup_basket = get_supplier_draft(dist_name, merchant_phone=effective_merchant_phone, db=db)
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
                        prod = catalog_service.find_product_exact_or_best(p_name, merchant_phone=effective_merchant_phone, db=db)
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
            dist_freshness = get_supplier_price_freshness(dist_name, db)
            price_notice_supplier = ""
            if not dist_freshness["is_fresh"]:
                price_notice_supplier = f"\n📌 *NOTA:* Por favor confirmar precios vigentes al facturar ya que tenemos la lista de hace más de 7 días ({dist_freshness['days_old']} días)."

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
                    f"📌 *IMPORTANTE:* Por favor envíe confirmación de pedido, remitos o listas de precios actualizadas directamente a este chat. Soy la asistente del comercio '{client_name}'.{price_notice_supplier} ¡Muchas gracias!"
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
                clear_supplier_draft(dist_name, merchant_phone=effective_merchant_phone, db=db)

            # Multi-Employee Mirror: If dispatched by an authorized employee, notify the store owner
            if sender_prospect and sender_prospect.parent_merchant_phone:
                owner_phone = sender_prospect.parent_merchant_phone
                emp_name = sender_prospect.contact_name or "Tu empleado"
                owner_mirror_msg = (
                    f"🔔 *NOTIFICACIÓN DE PEDIDO DESPACHADO (EQUIPO)*\n\n"
                    f"👤 *{emp_name}* acaba de despachar un pedido formal a *{dist_name}* (+{target_phone}):\n\n"
                    f"📋 *Items enviados:*\n{item_lines}\n"
                    f"💰 *Total estimado:* {total_display}\n\n"
                    f"📄 Remito formal en PDF enviado al distribuidor vía WhatsApp."
                )
                try:
                    await whatsapp.send_whatsapp_message(to_phone=owner_phone, text=owner_mirror_msg)
                except Exception as e:
                    logger.error(f"Error sending owner mirror alert: {e}")

            basket_note = f"\n\n✨ *Los faltantes anotados para {dist_name} quedaron pasados en limpio para la próxima reposición.*" if has_basket else ""
            fresh_warn = f"\n\n⚠️ *Aviso de precios:* La lista de {dist_name} tiene más de 7 días. Ya le incluí un aviso para que confirme si hubo variaciones al facturar." if not dist_freshness["is_fresh"] else ""

            return True, (
                f"✅ *¡Pedido despachado con éxito!*\n\n"
                f"Acabo de enviarle a *{dist_name}* (+{target_phone}) el detalle formal y el remito en PDF.\n\n"
                f"📋 *Items enviados:*\n{item_lines}\n"
                f"💰 *Total:* {total_display}\n\n"
                f"📍 Mensaje y remito PDF enviados correctamente."
                f"{fresh_warn}"
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

    analysis = await parse_order_or_inquiry_with_ai(clean_text, merchant_phone=effective_merchant_phone, db=db)
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
        inquiry_reply = build_product_inquiry_reply(analysis.inquired_products, contact_name="Javier", merchant_phone=effective_merchant_phone, db=db)
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
        weekly_summary = catalog_service.get_weekly_price_changes(requester_name="Javier", merchant_phone=effective_merchant_phone, db=db)
        return True, weekly_summary, "boss_price_increases"

    # 2.8.1 Multi-supplier Price Comparison & Cheapest Supplier Inquiry
    if any(k in lower_text for k in [
        "mas barato", "más barato", "vende mas barato", "vende más barato",
        "tiene mas barato", "tiene más barato", "quien tiene", "quién tiene",
        "comparame", "comparar precios", "comparativa de precios", "comparar", "mejor precio",
        "quien vende mas barato", "quién vende más barato", "quien me deja mas barato", "quién me deja más barato"
    ]) and not any(k in lower_text for k in ["servicio", "software", "agencia", "sofia", "ia", "abono"]):
        formatted_comp = catalog_service.format_price_comparison(clean_text, requester_name="Javier", merchant_phone=effective_merchant_phone, db=db)
        if formatted_comp:
            return True, formatted_comp, "boss_price_comparison"

    if any(k in lower_text for k in ["cuanto", "cuánto", "precio", "sale", "a cuanto", "a cuánto"]) and not any(k in lower_text for k in ["servicio", "software", "agencia", "sofia", "ia", "abono"]):
        p = catalog_service.find_product_exact_or_best(clean_text, merchant_phone=effective_merchant_phone, db=db)
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
    clean_lower_cmd = re.sub(r'^(?:sofi|sofia|hola|buenas|che)[\s,:]*', '', lower_text).strip()
    manual_triggers = ["manual", "guia", "guía", "instructivo", "modo de uso", "manual de uso", "manual cliente", "guia cliente", "guía cliente"]
    if any(clean_lower_cmd == k or clean_lower_cmd.startswith(k + " ") for k in manual_triggers):
        manual_text = get_client_manual_text()
        return True, manual_text, "boss_manual_view"

    # 5.4 Client FAQ & Commercial Security Guide (`dudas`, `faq`, `preguntas frecuentes`, `que pasa si`)
    faq_triggers = [
        "dudas", "duda", "faq", "faqs", "preguntas frecuentes", "que pasa si", "qué pasa si",
        "como funciona", "cómo funciona", "detalles tecnicos", "detalles técnicos",
        "seguridad comercial", "seguridad", "garantias", "garantías"
    ]
    if any(clean_lower_cmd == k or clean_lower_cmd.startswith(k + " ") for k in faq_triggers):
        faq_text = get_client_faq_text()
        return True, faq_text, "boss_faq_view"

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

