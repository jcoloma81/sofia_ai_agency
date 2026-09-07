import re
import json
import base64
import logging
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.prospect import Prospect
from app.services import brain, whatsapp
from app.config.settings import settings
from app.services.boss_mode import is_boss_number, process_boss_message
from app.services.catalog import catalog_service
from app.services.order_engine import (
    parse_order_text,
    format_order_summary_message,
    detect_order_intent,
    is_order_confirmation
)

logger = logging.getLogger(__name__)

router = APIRouter()

PROCESSED_MESSAGE_IDS = set()

class WebhookMessagePayload(BaseModel):
    phone: str
    message: str
    contact_name: Optional[str] = None
    complex_name: Optional[str] = None
    city: Optional[str] = None

@router.get("/webhook")
def verify_webhook_ping():
    return {"status": "ok", "service": "Sofía AI Agency Webhook"}

@router.post("/webhook")
async def receive_whatsapp_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Receives incoming WhatsApp messages from prospects or human agents.
    Features:
    - Whapi.cloud payload parsing
    - Webhook deduplication
    - Human takeover detection (silencing Sofia for that prospect)
    - Remote reactivation by Javier from his private line
    - Voice note audio downloading & multimodal processing
    - AI Brain generation
    - Dual alert triggering upon meeting scheduling
    """
    body = await request.json()
    logger.info(f"Incoming WhatsApp webhook payload: {body}")

    phone = ""
    message = ""
    contact_name = None
    audio_b64 = None
    audio_mime = None
    doc_bytes = None
    doc_name = None

    # 1. Handle Whapi.Cloud format
    if "messages" in body and isinstance(body["messages"], list) and len(body["messages"]) > 0:
        first_msg = body["messages"][0]

        # Check if message is sent by ourselves
        if first_msg.get("from_me") is True:
            # If sent from mobile or web, Javier typed manually!
            # Activate human_takeover ONLY for this specific prospect
            if first_msg.get("source") in ["mobile", "web"]:
                chat_id = str(first_msg.get("chat_id", ""))
                clean_recipient = "".join(filter(str.isdigit, chat_id.split("@")[0]))
                if clean_recipient:
                    target_lead = db.query(Prospect).filter(Prospect.phone == clean_recipient).first()
                    if target_lead:
                        target_lead.status = "human_takeover"
                        manual_text = first_msg.get("text", {}).get("body", "") if isinstance(first_msg.get("text"), dict) else first_msg.get("body", "")
                        if manual_text:
                            try:
                                history = json.loads(target_lead.conversation_history or "[]")
                            except Exception:
                                history = []
                            history.append({
                                "sender": "javier_human",
                                "text": str(manual_text).strip(),
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            })
                            target_lead.conversation_history = json.dumps(history, ensure_ascii=False)
                        db.commit()
                        logger.info(f"👤 Human Takeover activated for chat {clean_recipient}. Sofia will stay silent on this chat.")
                return {"status": "success", "reason": "Human takeover recorded"}

            # Default for API or tests: ignore self messages
            return {"status": "ignored", "reason": "Self message ignored"}

        # Prevent duplicate handling from webhook retries
        msg_id = first_msg.get("id")
        if msg_id:
            if msg_id in PROCESSED_MESSAGE_IDS:
                return {"status": "ignored", "reason": "Duplicate message ID"}
            PROCESSED_MESSAGE_IDS.add(msg_id)
            if len(PROCESSED_MESSAGE_IDS) > 2000:
                PROCESSED_MESSAGE_IDS.pop()

        chat_id = str(first_msg.get("chat_id", ""))
        sender = str(first_msg.get("from", ""))
        if chat_id.endswith("@s.whatsapp.net"):
            phone = chat_id.split("@")[0]
        elif sender and not sender.endswith("@lid"):
            phone = sender.split("@")[0]
        else:
            phone = chat_id.split("@")[0] or sender.split("@")[0]

        contact_name = first_msg.get("from_name")

        # Audio / Voice extraction
        msg_type = first_msg.get("type")
        if msg_type in ["voice", "audio"]:
            voice_data = first_msg.get("voice") or first_msg.get("audio") or {}
            audio_link = voice_data.get("link") or first_msg.get("link")
            audio_mime = voice_data.get("mime_type") or "audio/ogg"
            if audio_link:
                try:
                    headers = {}
                    if "gate.whapi.cloud" in audio_link and settings.WHATSAPP_API_TOKEN:
                        headers["Authorization"] = f"Bearer {settings.WHATSAPP_API_TOKEN}"
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        audio_res = await client.get(audio_link, headers=headers)
                        if audio_res.status_code == 200:
                            audio_b64 = base64.b64encode(audio_res.content).decode("utf-8")
                            message = "(Nota de voz enviada por el cliente)"
                            logger.info(f"🎙️ WhatsApp voice note downloaded ({len(audio_res.content)} bytes) for {phone}")
                except Exception as audio_err:
                    logger.error(f"Error downloading WhatsApp voice note from {audio_link}: {audio_err}")
        elif msg_type == "document":
            doc_data = first_msg.get("document") or {}
            doc_link = doc_data.get("link") or first_msg.get("link")
            doc_name = doc_data.get("filename") or first_msg.get("filename") or "documento"
            if doc_link:
                try:
                    headers = {}
                    if "gate.whapi.cloud" in doc_link and settings.WHATSAPP_API_TOKEN:
                        headers["Authorization"] = f"Bearer {settings.WHATSAPP_API_TOKEN}"
                    async with httpx.AsyncClient(timeout=20.0) as client:
                        doc_res = await client.get(doc_link, headers=headers)
                        if doc_res.status_code == 200:
                            doc_bytes = doc_res.content
                            message = f"(Documento adjunto recibido: {doc_name})"
                            logger.info(f"📁 WhatsApp document downloaded ({len(doc_bytes)} bytes): {doc_name}")
                except Exception as doc_err:
                    logger.error(f"Error downloading WhatsApp document from {doc_link}: {doc_err}")

        # Text extraction (if not voice note or document)
        if not message:
            if isinstance(first_msg.get("text"), dict):
                message = first_msg["text"].get("body", "")
            else:
                message = first_msg.get("body", "") or first_msg.get("text", "")

        # Incorporate quoted context if present
        quoted = first_msg.get("context", {}).get("quoted_content", {}).get("body")
        if quoted and quoted.strip() and quoted not in message:
            message = f"{message} [En respuesta a: \"{quoted.strip()}\"]"

    # 2. Handle nested Baileys/Evolution API format
    elif not message and isinstance(body.get("data"), dict):
        data = body["data"]
        phone = data.get("key", {}).get("remoteJid", "").split("@")[0] or phone
        message = data.get("message", {}).get("conversation", "") or ""

    # 3. Direct/standard test format
    if not message:
        phone = phone or body.get("phone") or body.get("from") or body.get("sender") or ""
        message = body.get("message") or body.get("text") or body.get("body") or ""
        contact_name = contact_name or body.get("contact_name")

    clean_phone = "".join(filter(str.isdigit, str(phone)))
    if not clean_phone or not message:
        return {"status": "ignored", "reason": "Missing phone or message"}

    # Executive command check from Javier's personal alert line (Modo Jefe)
    if is_boss_number(clean_phone):
        handled, boss_reply, boss_action = await process_boss_message(
            db=db,
            sender_phone=clean_phone,
            text=message,
            doc_bytes=doc_bytes,
            doc_name=doc_name
        )
        if handled:
            await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=boss_reply)
            return {"status": "success", "action": boss_action, "reply": boss_reply}

    # Find or create prospect
    prospect = db.query(Prospect).filter(Prospect.phone == clean_phone).first()
    if not prospect:
        prospect = Prospect(
            phone=clean_phone,
            name=body.get("complex_name") or body.get("name") or f"Prospecto ({clean_phone})",
            contact_name=body.get("contact_name") or contact_name,
            city=body.get("city") or "Entre Ríos / Santa Fe",
            campaign="ai_agency",
            status="in_conversation",
            conversation_history="[]"
        )
        db.add(prospect)
        db.commit()
        db.refresh(prospect)

    # If this specific prospect is in human_takeover, Sofia remains completely silent!
    if prospect.status == "human_takeover":
        try:
            history = json.loads(prospect.conversation_history or "[]")
        except Exception:
            history = []
        history.append({
            "sender": "prospect",
            "text": message.strip(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        prospect.conversation_history = json.dumps(history, ensure_ascii=False)
        prospect.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Prospect {clean_phone} is in human_takeover. Sofia remains silent.")
        return {"status": "ignored", "reason": "Prospect in human_takeover mode (Sofia silenced for this chat)"}

    # Parse and update conversation history
    try:
        history = json.loads(prospect.conversation_history or "[]")
    except Exception:
        history = []

    history_text = "🎙️ [Nota de voz recibida]" if audio_b64 else message.strip()
    history.append({
        "sender": "prospect",
        "text": history_text,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    # 1. Check if prospect is confirming an existing pending order
    is_confirming_order = False
    pending_order = None
    if prospect.notes:
        try:
            notes_dict = json.loads(prospect.notes)
            if isinstance(notes_dict, dict) and notes_dict.get("type") == "PEDIDO_PENDIENTE":
                if is_order_confirmation(message):
                    is_confirming_order = True
                    pending_order = notes_dict
        except Exception:
            pass

    if is_confirming_order and pending_order:
        class DummyItem:
            def __init__(self, name, presentation, qty, subtotal):
                self.product = type("P", (), {
                    "name": name,
                    "presentation": presentation,
                    "formatted_price": lambda: f"${int(subtotal/qty):,}".replace(",", ".") if qty > 0 else "$0"
                })()
                self.quantity = qty
                self.formatted_subtotal = lambda: f"${int(subtotal):,}".replace(",", ".")
                self.in_stock = True

        class DummyDraft:
            def __init__(self, items, total_str):
                self.items = items
                self.formatted_total = lambda: total_str

        dummy_items = [
            DummyItem(it["name"], it.get("presentation", "Unidad"), it["qty"], it.get("subtotal", 0))
            for it in pending_order.get("items", [])
        ]
        dummy_draft = DummyDraft(dummy_items, pending_order.get("total_str", "$0"))

        prospect.status = "order_confirmed"
        prospect.meeting_details = f"Pedido: {pending_order.get('total_str', '')}"
        prospect.notes = json.dumps({
            "type": "PEDIDO_CONFIRMADO",
            "items": pending_order.get("items", []),
            "total_str": pending_order.get("total_str", "")
        })

        contact_str = f" {prospect.contact_name}" if prospect.contact_name else ""
        order_confirmed_reply = (
            f"¡Excelente{contact_str}! Tu pedido ya fue ingresado a depósito para preparar el despacho. "
            f"En breve te avisamos cuando salga el camión de reparto. ¡Muchas gracias!"
        )

        history.append({"sender": "ai", "text": order_confirmed_reply, "timestamp": datetime.now(timezone.utc).isoformat()})
        prospect.conversation_history = json.dumps(history, ensure_ascii=False)
        prospect.updated_at = datetime.now(timezone.utc)
        db.commit()

        asyncio.create_task(whatsapp.notify_owner_order_confirmed(
            client_name=prospect.name,
            contact_name=prospect.contact_name,
            phone=prospect.phone,
            city=prospect.city,
            order_draft=dummy_draft
        ))

        await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=order_confirmed_reply)
        return {
            "status": "success",
            "order_confirmed": True,
            "reply": order_confirmed_reply,
            "meeting_confirmed": False
        }

    # 2. Check if customer wants to place a new order
    order_triggers = ["caja", "fardo", "pack", "bolsa", "aceite", "harina", "arroz", "fideo", "yerba", "leche", "queso", "coca", "quilmes", "cajon", "cajón"]
    if detect_order_intent(message) or (len(re.findall(r'\d+', message)) > 0 and any(k in message.lower() for k in order_triggers)):
        draft = parse_order_text(message)
        if draft.items:
            order_summary = format_order_summary_message(draft, prospect.contact_name)
            prospect.notes = json.dumps({
                "type": "PEDIDO_PENDIENTE",
                "items": [
                    {"name": it.product.name, "presentation": it.product.presentation, "qty": it.quantity, "subtotal": it.subtotal}
                    for it in draft.items if it.in_stock
                ],
                "total": draft.total,
                "total_str": draft.formatted_total()
            })
            history.append({"sender": "ai", "text": order_summary, "timestamp": datetime.now(timezone.utc).isoformat()})
            prospect.conversation_history = json.dumps(history, ensure_ascii=False)
            prospect.updated_at = datetime.now(timezone.utc)
            db.commit()

            await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=order_summary)
            return {
                "status": "success",
                "order_draft": True,
                "reply": order_summary,
                "meeting_confirmed": False
            }

    # 3. Check if customer asks about a specific product's price
    if any(k in message.lower() for k in ["cuanto", "cuánto", "precio", "sale", "tenes", "tenés", "a cuanto", "a cuánto"]) and catalog_service.products:
        if not any(k in message.lower() for k in ["servicio", "software", "agencia", "sofia", "ia", "abono"]):
            found_prod = catalog_service.find_product_exact_or_best(message)
            if found_prod:
                stock_info = "tenemos stock disponible" if found_prod.in_stock else "actualmente figura sin stock"
                contact_str = f" {prospect.contact_name}" if prospect.contact_name else ""
                price_reply = (
                    f"¡Hola{contact_str}! El *{found_prod.name}* ({found_prod.presentation}) "
                    f"está a *{found_prod.formatted_price()}* y {stock_info}. "
                    f"¿Cuántas unidades te anoto para el próximo reparto?"
                )
                history.append({"sender": "ai", "text": price_reply, "timestamp": datetime.now(timezone.utc).isoformat()})
                prospect.conversation_history = json.dumps(history, ensure_ascii=False)
                prospect.updated_at = datetime.now(timezone.utc)
                db.commit()

                await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=price_reply)
                return {
                    "status": "success",
                    "price_quote": True,
                    "reply": price_reply,
                    "meeting_confirmed": False
                }

    # Generate response via AI Brain
    ai_response, is_meeting_confirmed, meeting_details = await brain.generate_ai_response(
        incoming_text=message.strip(),
        conversation_history=history,
        prospect_name=prospect.name,
        contact_name=prospect.contact_name,
        city=prospect.city,
        audio_data_b64=audio_b64,
        audio_mime_type=audio_mime,
        campaign=prospect.campaign or "ai_agency"
    )

    # Append AI response to history
    history.append({
        "sender": "ai",
        "text": ai_response.strip(),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    prospect.conversation_history = json.dumps(history, ensure_ascii=False)
    prospect.updated_at = datetime.now(timezone.utc)

    # If meeting was confirmed, trigger dual alert to Javier
    if is_meeting_confirmed:
        prospect.status = "meeting_scheduled"
        prospect.meeting_details = meeting_details or message.strip()
        prospect.meeting_scheduled_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(prospect)

        logger.info(f"🎯 MEETING CONFIRMED with {prospect.name}! Details: {prospect.meeting_details} [campaign={prospect.campaign}]")
        last_msg_display = f"🎙️ Nota de voz ({meeting_details})" if audio_b64 and meeting_details else message.strip()
        asyncio.create_task(whatsapp.notify_javier_meeting_scheduled(
            prospect_name=prospect.name,
            contact_name=prospect.contact_name,
            phone=prospect.phone,
            city=prospect.city,
            meeting_details=prospect.meeting_details,
            last_message=last_msg_display,
            campaign=prospect.campaign or "ai_agency"
        ))
    else:
        if prospect.status == "pending":
            prospect.status = "in_conversation"
        db.commit()
        db.refresh(prospect)

    # Send response back to prospect via WhatsApp
    await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=ai_response)

    # Check if prospect requested proposal / catalog / PDF
    if brain.detect_catalog_request(message) or any(k in ai_response.lower() for k in ["adjuntar nuestra propuesta", "adjunto nuestra propuesta", "propuesta en pdf"]):
        base_url = settings.APP_BASE_URL.rstrip('/')
        if "127.0.0.1" in base_url or "localhost" in base_url:
            base_url = "https://sofia-ai-agency.onrender.com"
        pdf_url = f"{base_url}/assets/propuesta_sofia_ai_agency.pdf"
        
        logger.info(f"📄 Automatically dispatching corporate proposal PDF to {clean_phone}")
        asyncio.create_task(whatsapp.send_whatsapp_document(
            to_phone=clean_phone,
            document_url=pdf_url,
            filename="Propuesta_Comercial_Sofia_IA.pdf",
            caption="📄 Propuesta Comercial — Sofía AI Agency"
        ))

    return {
        "status": "success",
        "reply": ai_response,
        "meeting_confirmed": is_meeting_confirmed,
        "meeting_details": meeting_details
    }
