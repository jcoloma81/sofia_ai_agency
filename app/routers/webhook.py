import re
import json
import base64
import logging
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.prospect import Prospect, WebhookEvent
from app.services import brain, whatsapp
from app.config.settings import settings
from app.services.boss_mode import is_boss_number, process_boss_message
from app.services.catalog import catalog_service, parse_supplier_price_update_text
from app.services.order_engine import (
    parse_order_text,
    format_order_summary_message,
    detect_order_intent,
    is_order_confirmation,
    parse_order_or_inquiry_with_ai,
    build_product_inquiry_reply
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

@router.get("/events")
def get_recent_webhook_events(db: Session = Depends(get_db)):
    events = db.query(WebhookEvent).order_by(WebhookEvent.id.desc()).limit(15).all()
    return [{"id": e.id, "created_at": str(e.created_at), "payload": json.loads(e.payload) if e.payload else {}} for e in events]

@router.get("/webhook")
def verify_webhook_ping(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token")
):
    """
    Handles both:
    1. Official Meta WhatsApp Cloud API verification handshake (GET with hub.mode, hub.challenge, hub.verify_token).
    2. General healthcheck pings from browsers or uptime monitors.
    """
    if hub_mode == "subscribe":
        expected_token = settings.META_VERIFY_TOKEN
        if hub_verify_token == expected_token:
            logger.info(f"✅ Meta Webhook verification successful! Returning challenge: {hub_challenge}")
            return PlainTextResponse(content=str(hub_challenge or ""), status_code=200)
        else:
            logger.warning(f"❌ Meta Webhook verification failed: verify_token mismatch ({hub_verify_token})")
            return PlainTextResponse(content="Verification token mismatch", status_code=403)

    return {"status": "ok", "service": "Sofía AI Agency Webhook"}

@router.post("/webhook")
async def receive_whatsapp_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Receives incoming WhatsApp messages from prospects or human agents.
    """
    body = await request.json()
    logger.info(f"Incoming WhatsApp webhook payload: {body}")

    # Persist raw webhook payload for debugging & traceability
    try:
        raw_event = WebhookEvent(payload=json.dumps(body))
        db.add(raw_event)
        db.commit()
    except Exception as log_err:
        logger.error(f"Error persisting webhook event: {log_err}")

    phone = ""
    message = ""
    contact_name = None
    audio_b64 = None
    audio_mime = None
    doc_bytes = None
    doc_name = None
    is_incoming_voice = False

    # 0. Handle Official Meta WhatsApp Cloud API format (Production & Dashboard Test Tool)
    if body.get("object") == "whatsapp_business_account" or ("value" in body and isinstance(body.get("value"), dict) and "messages" in body["value"]):
        incoming_meta_msg = None
        meta_contacts = []

        if body.get("object") == "whatsapp_business_account":
            entries = body.get("entry", [])
            for entry in entries:
                changes = entry.get("changes", [])
                for change in changes:
                    value = change.get("value", {})
                    if "messages" in value and isinstance(value["messages"], list) and len(value["messages"]) > 0:
                        incoming_meta_msg = value["messages"][0]
                        meta_contacts = value.get("contacts", [])
                        break
                if incoming_meta_msg:
                    break
        elif "value" in body:
            value = body["value"]
            if "messages" in value and isinstance(value["messages"], list) and len(value["messages"]) > 0:
                incoming_meta_msg = value["messages"][0]
                meta_contacts = value.get("contacts", [])

        if not incoming_meta_msg:
            # It was a status update (sent, delivered, read) or non-message event from Meta
            logger.info("Meta webhook event received (status update or non-message event)")
            return {"status": "success", "reason": "Meta status or non-message event received"}

        # Prevent duplicate handling from webhook retries
        msg_id = incoming_meta_msg.get("id")
        if msg_id:
            if msg_id in PROCESSED_MESSAGE_IDS:
                return {"status": "ignored", "reason": "Duplicate message ID"}
            PROCESSED_MESSAGE_IDS.add(msg_id)
            if len(PROCESSED_MESSAGE_IDS) > 2000:
                PROCESSED_MESSAGE_IDS.pop()

        phone = incoming_meta_msg.get("from", "")
        if meta_contacts and isinstance(meta_contacts, list) and len(meta_contacts) > 0:
            contact_name = meta_contacts[0].get("profile", {}).get("name")

        msg_type = incoming_meta_msg.get("type")
        if msg_type == "text":
            message = incoming_meta_msg.get("text", {}).get("body", "")
        elif msg_type == "interactive":
            interactive = incoming_meta_msg.get("interactive", {})
            if interactive.get("type") == "button_reply":
                message = interactive.get("button_reply", {}).get("title", "")
            elif interactive.get("type") == "list_reply":
                message = interactive.get("list_reply", {}).get("title", "")
        elif msg_type in ["voice", "audio"]:
            is_incoming_voice = True
            audio_info = incoming_meta_msg.get("audio") or incoming_meta_msg.get("voice") or {}
            media_id = audio_info.get("id")
            audio_mime = audio_info.get("mime_type", "audio/ogg")
            if media_id and settings.META_ACCESS_TOKEN:
                try:
                    meta_headers = {"Authorization": f"Bearer {settings.META_ACCESS_TOKEN}"}
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        info_res = await client.get(f"https://graph.facebook.com/v20.0/{media_id}", headers=meta_headers)
                        if info_res.status_code == 200:
                            download_url = info_res.json().get("url")
                            if download_url:
                                audio_res = await client.get(download_url, headers=meta_headers)
                                if audio_res.status_code == 200:
                                    audio_b64 = base64.b64encode(audio_res.content).decode("utf-8")
                                    transcription = await brain.transcribe_audio_gemini(audio_b64, audio_mime)
                                    if transcription:
                                        message = transcription
                                        logger.info(f"🎙️ Meta voice note transcribed: '{message}'")
                                    else:
                                        message = "(Nota de voz recibida)"
                                    logger.info(f"🎙️ Meta voice note downloaded ({len(audio_res.content)} bytes) for {phone}")
                except Exception as audio_err:
                    logger.error(f"Error processing Meta voice note: {audio_err}")
        elif msg_type == "document":
            doc_info = incoming_meta_msg.get("document", {})
            media_id = doc_info.get("id")
            doc_name = doc_info.get("filename") or "documento.pdf"
            if media_id and settings.META_ACCESS_TOKEN:
                try:
                    meta_headers = {"Authorization": f"Bearer {settings.META_ACCESS_TOKEN}"}
                    async with httpx.AsyncClient(timeout=20.0) as client:
                        info_res = await client.get(f"https://graph.facebook.com/v20.0/{media_id}", headers=meta_headers)
                        if info_res.status_code == 200:
                            download_url = info_res.json().get("url")
                            if download_url:
                                doc_res = await client.get(download_url, headers=meta_headers)
                                if doc_res.status_code == 200:
                                    doc_bytes = doc_res.content
                                    message = f"(Documento adjunto recibido: {doc_name})"
                                    logger.info(f"📁 Meta document downloaded ({len(doc_bytes)} bytes): {doc_name}")
                except Exception as doc_err:
                    logger.error(f"Error processing Meta document: {doc_err}")
        elif msg_type == "contacts":
            contacts_list = incoming_meta_msg.get("contacts", [])
            if contacts_list and isinstance(contacts_list, list):
                c_item = contacts_list[0]
                c_name_obj = c_item.get("name", {})
                c_name = c_name_obj.get("formatted_name") or c_name_obj.get("first_name") or "Proveedor"
                c_phones = c_item.get("phones", [])
                c_phone = ""
                if c_phones and isinstance(c_phones, list):
                    c_phone = c_phones[0].get("phone") or c_phones[0].get("wa_id") or ""
                c_phone_digits = "".join(filter(str.isdigit, c_phone))
                message = f"agendá al proveedor {c_name} al {c_phone_digits}"
                logger.info(f"📇 Meta contact received: '{c_name}' -> '{c_phone_digits}'")

    # 1. Handle Whapi.Cloud format
    elif "messages" in body and isinstance(body["messages"], list) and len(body["messages"]) > 0:
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
                            # Transcribe voice note so Boss mode and Order engine can process spoken words
                            transcription = await brain.transcribe_audio_gemini(audio_b64, audio_mime)
                            if transcription:
                                message = transcription
                                logger.info(f"🎙️ WhatsApp voice note transcribed: '{message}'")
                            else:
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
        elif msg_type in ["contact", "contacts"]:
            contact_data = first_msg.get("contact") or (first_msg.get("contacts", [{}])[0] if isinstance(first_msg.get("contacts"), list) and len(first_msg.get("contacts")) > 0 else {})
            c_name = contact_data.get("name") or "Proveedor"
            vcard_text = contact_data.get("vcard", "")
            raw_phone = phone_m.group(1) if phone_m else contact_data.get("phone", "")
            c_phone_digits = "".join(filter(str.isdigit, raw_phone))
            message = f"agendá al proveedor {c_name} al {c_phone_digits}"
            logger.info(f"📇 Whapi contact received: '{c_name}' -> '{c_phone_digits}'")

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
        if not doc_bytes and body.get("doc_base64"):
            doc_bytes = base64.b64decode(body["doc_base64"])
            doc_name = body.get("doc_name", "catalogo.xlsx")
            if not message:
                message = f"(Documento adjunto recibido: {doc_name})"

    clean_phone = "".join(filter(str.isdigit, str(phone)))
    if not clean_phone or not message:
        return {"status": "ignored", "reason": "Missing phone or message"}

    # Executive command check from Javier's personal alert line (Modo Jefe)
    if is_boss_number(clean_phone):
        boss_record = db.query(Prospect).filter(Prospect.phone == clean_phone).first()

        # Check if boss is running a live Prospect Simulation
        if boss_record and boss_record.campaign == "ai_agency" and boss_record.status in ["contacted", "in_conversation"]:
            clean_cmd = message.strip().lower()
            if clean_cmd in ["modo jefe", "salir de prueba", "terminar prueba", "fin prueba"]:
                boss_record.status = "director"
                boss_record.name = "Javier Coloma (Director)"
                boss_record.campaign = "boss_mode"
                db.commit()
                revert_msg = "✅ Simulación finalizada. Has vuelto a Modo Jefe (Director)."
                await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=revert_msg)
                return {"status": "success", "action": "exit_simulation", "reply": revert_msg}
            logger.info(f"🧪 Boss number {clean_phone} is in PROSPECT SIMULATION mode ('{boss_record.name}'). Falling through to prospect flow.")
        else:
            if not boss_record:
                boss_record = Prospect(
                    phone=clean_phone,
                    name="Javier Coloma (Director)",
                    contact_name="Javier",
                    city="Paraná / Central",
                    campaign="boss_mode",
                    status="director",
                    conversation_history="[]"
                )
                db.add(boss_record)
                db.commit()
                db.refresh(boss_record)

            try:
                boss_history = json.loads(boss_record.conversation_history or "[]")
            except Exception:
                boss_history = []

            history_item_text = "🎙️ [Nota de voz recibida]" if audio_b64 else message.strip()
            boss_history.append({
                "sender": "boss",
                "text": history_item_text,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

            handled, boss_reply, boss_action = await process_boss_message(
                db=db,
                sender_phone=clean_phone,
                text=message,
                doc_bytes=doc_bytes,
                doc_name=doc_name,
                conversation_history=boss_history
            )
            if handled:
                boss_history.append({
                    "sender": "ai",
                    "text": boss_reply.strip(),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                boss_record.conversation_history = json.dumps(boss_history, ensure_ascii=False)
                boss_record.updated_at = datetime.now(timezone.utc)
                db.commit()

                await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=boss_reply)
                if getattr(settings, "ENABLE_VOICE_RESPONSES", False) and (is_incoming_voice or clean_phone in ["5493434536447", "543434536447"]):
                    try:
                        from app.services.voice import text_to_speech_bytes
                        audio_bytes = await text_to_speech_bytes(boss_reply)
                        if audio_bytes:
                            await whatsapp.send_whatsapp_audio(to_phone=clean_phone, audio_bytes=audio_bytes)
                            logger.info(f"🎙️ Sent boss voice response audio to {clean_phone}")
                    except Exception as v_err:
                        logger.error(f"Error generating boss voice response: {v_err}")

                return {"status": "success", "action": boss_action, "reply": boss_reply}

    # Find or create prospect
    prospect = db.query(Prospect).filter(Prospect.phone == clean_phone).first()
    if not prospect:
        default_city = "Feira de Santana / Bahia (Brasil)" if clean_phone.startswith("55") else "Entre Ríos / Santa Fe"
        prospect = Prospect(
            phone=clean_phone,
            name=body.get("complex_name") or body.get("name") or f"Prospecto ({clean_phone})",
            contact_name=body.get("contact_name") or contact_name,
            city=body.get("city") or default_city,
            campaign="ai_agency",
            status="in_conversation",
            conversation_history="[]"
        )
        db.add(prospect)
        db.commit()
        db.refresh(prospect)

    # If this specific prospect is in human_takeover, check if 6 hours have passed
    if prospect.status == "human_takeover":
        last_update = prospect.updated_at
        if last_update:
            if last_update.tzinfo is None:
                last_update = last_update.replace(tzinfo=timezone.utc)
            elapsed_seconds = (datetime.now(timezone.utc) - last_update).total_seconds()
            if elapsed_seconds > 6 * 3600:
                logger.info(f"⏰ Auto-reactivating Sofia for {clean_phone}: 6 hours of human takeover have elapsed.")
                prospect.status = "in_conversation"
                prospect.updated_at = datetime.now(timezone.utc)
                db.commit()

        # If STILL in human_takeover (within 6 hours), log message and remain silent
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
            logger.info(f"Prospect {clean_phone} is in human_takeover (within 6h window). Sofia remains silent.")
            return {"status": "ignored", "reason": "Prospect in human_takeover mode (Sofia silenced for this chat)"}

    # Parse and update conversation history
    try:
        history = json.loads(prospect.conversation_history or "[]")
    except Exception:
        history = []

    # 0. Opt-out / BAJA handling (compliant with footer "Respondé BAJA...")
    clean_msg_lower = message.strip().lower().strip('"').strip("'")
    if clean_msg_lower in [
        "baja", "cancelar", "stop", "desuscribir", "no me interesa", "dar de baja",
        "ahora no, gracias", "ahora no gracias", "ahora no", "no gracias", "no, gracias"
    ]:
        prospect.status = "unsubscribed"
        history.append({
            "sender": "prospect",
            "text": message.strip(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        baja_reply = "Entendido. Ya te dimos de baja para no enviarte más mensajes. ¡Muchas gracias y que tengas un excelente día!"
        history.append({
            "sender": "ai",
            "text": baja_reply,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        prospect.conversation_history = json.dumps(history, ensure_ascii=False)
        prospect.updated_at = datetime.now(timezone.utc)
        db.commit()
        await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=baja_reply)
        logger.info(f"🚫 Prospect {clean_phone} requested opt-out (BAJA). Unsubscribed successfully.")
        return {"status": "success", "action": "opt_out", "reply": baja_reply}

    if prospect.status == "unsubscribed":
        logger.info(f"🚫 Prospect {clean_phone} is unsubscribed. Ignoring message.")
        return {"status": "ignored", "reason": "Prospect is unsubscribed"}

    history_text = "🎙️ [Nota de voz recibida]" if audio_b64 else message.strip()
    history.append({
        "sender": "prospect",
        "text": history_text,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    # 0.5 Prospect document upload (supplier catalog, price list, PDF or Excel)
    if doc_bytes and doc_name:
        fname = doc_name.lower()
        if fname.endswith((".xlsx", ".xls", ".csv", ".pdf")):
            safe_name = brain.sanitize_contact_first_name(prospect.contact_name) or "amigo"
            count = 0
            if fname.endswith((".xlsx", ".xls")):
                count = catalog_service.load_from_excel_bytes(doc_bytes, filename=doc_name)
            elif fname.endswith(".csv"):
                try:
                    csv_str = doc_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    csv_str = doc_bytes.decode("latin-1", errors="ignore")
                count = catalog_service.load_from_csv(csv_str, source_name=doc_name)
            elif fname.endswith(".pdf"):
                count = await catalog_service.load_from_pdf_bytes(doc_bytes, filename=doc_name)

            if count > 0:
                doc_reply = (
                    f"¡Recibí tu lista *{doc_name}*, {safe_name}! 📁\n\n"
                    f"Ya procesé y sincronicé *{count} productos* en el catálogo. "
                    f"Ya podés consultarme precios o hacerme pedidos sobre cualquiera de estos artículos."
                )
                history.append({"sender": "ai", "text": doc_reply, "timestamp": datetime.now(timezone.utc).isoformat()})
                prospect.conversation_history = json.dumps(history, ensure_ascii=False)
                prospect.updated_at = datetime.now(timezone.utc)
                db.commit()

                # Alert the boss (Javier)
                if settings.WHATSAPP_ALERT_PHONE:
                    boss_alert = (
                        f"🔔 *Nuevo catálogo recibido de cliente*\n\n"
                        f"• *Cliente:* {prospect.name} ({prospect.contact_name or 'Titular'})\n"
                        f"• *Teléfono:* {prospect.phone}\n"
                        f"• *Archivo:* `{doc_name}`\n"
                        f"• *Artículos cargados:* {count}\n\n"
                        f"Sofía ya actualizó el catálogo activo automáticamente."
                    )
                    asyncio.create_task(whatsapp.send_whatsapp_message(to_phone=settings.WHATSAPP_ALERT_PHONE, text=boss_alert))

                await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=doc_reply)
                return {"status": "success", "action": "prospect_catalog_loaded", "count": count, "reply": doc_reply}
            else:
                doc_reply = f"Recibí el archivo `{doc_name}`, pero no pude extraer listas de precios automáticas. Verificá que contenga texto legible o tablas de productos."
                history.append({"sender": "ai", "text": doc_reply, "timestamp": datetime.now(timezone.utc).isoformat()})
                prospect.conversation_history = json.dumps(history, ensure_ascii=False)
                prospect.updated_at = datetime.now(timezone.utc)
                db.commit()
                await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=doc_reply)
                return {"status": "success", "action": "prospect_catalog_error", "reply": doc_reply}

    # 0.6 Incoming Supplier Messages: Price Updates or Registration Acknowledgments
    is_supplier_sender = (
        prospect.business_type == "proveedor"
        or prospect.campaign == "supplier"
        or (prospect.notes and "proveedor" in str(prospect.notes).lower())
    )
    if is_supplier_sender and message:
        # A. Acknowledgment of presentation ("Agendado", "Recibido", "Listo", etc.)
        if clean_msg_lower in [
            "agendado", "recibido", "agendada", "recibida", "listo", "dale", "ok", "buenisimo", "buenísimo",
            "perfecto", "agendados", "recibidos", "ya te agende", "ya te agendé", "agendado gracias", "recibido gracias"
        ]:
            sup_contact = brain.sanitize_contact_first_name(prospect.contact_name) or "amigo"
            ack_reply = (
                f"¡Muchas gracias, {sup_contact}! 🙌✨\n\n"
                f"Apenas el comercio tenga lista su reposición, te paso el pedido por acá detallado con códigos y en PDF para facilitarte la carga.\n\n"
                f"💡 Si tenés aumentos o cambios de lista vigentes, podés enviármelos por acá en cualquier momento (en archivo o simplemente escribiéndome qué sube). ¡Que tengas una excelente jornada! 📦"
            )
            history.append({"sender": "ai", "text": ack_reply, "timestamp": datetime.now(timezone.utc).isoformat()})
            prospect.conversation_history = json.dumps(history, ensure_ascii=False)
            prospect.updated_at = datetime.now(timezone.utc)
            db.commit()

            # Alert merchant and boss that supplier confirmed registration
            merchant_phone = None
            if prospect.notes:
                try:
                    meta_n = json.loads(prospect.notes)
                    if isinstance(meta_n, dict):
                        merchant_phone = meta_n.get("merchant_phone")
                except Exception:
                    pass

            if not merchant_phone:
                from app.services.boss_mode import get_active_onboarded_client
                active_c = get_active_onboarded_client(db)
                if active_c and active_c.get("phone"):
                    merchant_phone = active_c.get("phone")

            sup_biz = prospect.name or "Proveedor"
            alert_ack = (
                f"✅ *¡PROVEEDOR CONFIRMÓ RECEPCIÓN!* 📦\n\n"
                f"• *Proveedor:* {sup_biz}\n"
                f"• *Contacto:* {prospect.contact_name or 'Titular'}\n"
                f"• *Respuesta:* _«{message.strip()}»_\n\n"
                f"Sofía ya quedó agendada en su WhatsApp para pasarle los pedidos de tu comercio."
            )
            if merchant_phone and merchant_phone != clean_phone:
                asyncio.create_task(whatsapp.send_whatsapp_message(to_phone=merchant_phone, text=alert_ack))
            if settings.WHATSAPP_ALERT_PHONE and settings.WHATSAPP_ALERT_PHONE != clean_phone and settings.WHATSAPP_ALERT_PHONE != merchant_phone:
                asyncio.create_task(whatsapp.send_whatsapp_message(to_phone=settings.WHATSAPP_ALERT_PHONE, text=alert_ack))

            await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=ack_reply)
            return {"status": "success", "action": "supplier_acknowledged", "reply": ack_reply}

        # B. Informal Free-Text Price Update from Supplier
        price_upd_data = await parse_supplier_price_update_text(message)
        if price_upd_data.get("is_price_update") and price_upd_data.get("updates"):
            updates = price_upd_data["updates"]
            modified = catalog_service.process_supplier_price_updates(updates, supplier_name=prospect.name)
            sup_contact = brain.sanitize_contact_first_name(prospect.contact_name) or "amigo"

            sup_bullets = []
            for u in updates:
                p_brand = u.get("product_or_brand", "").title()
                if u.get("type") == "percentage":
                    sup_bullets.append(f"• *{p_brand}:* +{u.get('value')}%")
                else:
                    v = u.get("value", 0)
                    v_str = f"${int(v):,}".replace(",", ".") if float(v).is_integer() else f"${v:,.2f}"
                    sup_bullets.append(f"• *{p_brand}:* {v_str}")

            bullet_text = "\n".join(sup_bullets)
            supplier_reply = (
                f"¡Entendido, {sup_contact}! 👍 Ya registré los aumentos informados:\n\n"
                f"{bullet_text}\n\n"
                f"Muchas gracias por el aviso. Ya quedó actualizado en el catálogo para los próximos pedidos de reposición. 📋📦"
            )

            history.append({"sender": "ai", "text": supplier_reply, "timestamp": datetime.now(timezone.utc).isoformat()})
            prospect.conversation_history = json.dumps(history, ensure_ascii=False)
            prospect.updated_at = datetime.now(timezone.utc)
            db.commit()

            # Now alert the merchant
            merchant_lines = []
            if modified:
                for m in modified:
                    m_name = m["product"]
                    m_old = f"${int(m['old_price']):,}".replace(",", ".") if m['old_price'] > 0 else "Nuevo"
                    m_new = f"${int(m['new_price']):,}".replace(",", ".")
                    pct_str = f" (+{m['percentage']}%)" if m.get('percentage') else ""
                    merchant_lines.append(f"• *{m_name}:* {m_old} ➔ *{m_new}*{pct_str}")
            else:
                merchant_lines = sup_bullets

            merchant_phone = None
            if prospect.notes:
                try:
                    meta_n = json.loads(prospect.notes)
                    if isinstance(meta_n, dict):
                        merchant_phone = meta_n.get("merchant_phone")
                except Exception:
                    pass

            if not merchant_phone:
                from app.services.boss_mode import get_active_onboarded_client
                active_c = get_active_onboarded_client(db)
                if active_c and active_c.get("phone"):
                    merchant_phone = active_c.get("phone")

            merchant_alert = (
                f"🔔 *AVISO DE AUMENTO DE TU PROVEEDOR* 📈\n\n"
                f"🏢 *Proveedor:* {prospect.name} (+{clean_phone})\n"
                f"Acaba de informar actualizaciones de precios por WhatsApp:\n\n"
                f"{chr(10).join(merchant_lines)}\n\n"
                f"💡 *Sofía ya actualizó los costos en tu catálogo para que no pierdas margen en tus próximas ventas y pedidos de reposición.*"
            )

            if merchant_phone and merchant_phone != clean_phone:
                asyncio.create_task(whatsapp.send_whatsapp_message(to_phone=merchant_phone, text=merchant_alert))
            if settings.WHATSAPP_ALERT_PHONE and settings.WHATSAPP_ALERT_PHONE != clean_phone and settings.WHATSAPP_ALERT_PHONE != merchant_phone:
                asyncio.create_task(whatsapp.send_whatsapp_message(to_phone=settings.WHATSAPP_ALERT_PHONE, text=merchant_alert))

            await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=supplier_reply)
            return {"status": "success", "action": "supplier_price_updated", "reply": supplier_reply, "updates": updates}

    # 0.8 Merchant / Boss Directives from Client (e.g. dispatching orders to suppliers or managing baskets)
    merchant_dispatch_triggers = [
        "mandale el pedido a", "mandar pedido a", "pasar pedido a", "enviar pedido a",
        "mandale a", "mandá a", "hacele el pedido a", "hacé el pedido a",
        "despachar pedido a", "despachale a", "pasale el pedido a", "enviá el pedido a",
        "enviar a la distribuidora", "mandar a la distribuidora", "pasale a", "enviale a", "envíale a",
        "anota para", "anotame para", "anotá para", "pedidos a proveedores", "pedidos pendientes"
    ]
    merchant_supplier_triggers = [
        "agendá al proveedor", "agenda al proveedor", "agendar proveedor", "agendá a", "agenda a", "agendar a",
        "anotá al proveedor", "anota al proveedor", "anotar proveedor", "guardá al proveedor", "guarda al proveedor",
        "guardar proveedor", "nuevo proveedor", "proveedor nuevo", "el proveedor es", "el proveedor de",
        "agendá al viajante", "agenda al viajante", "agendar viajante", "anotá al viajante", "anota al viajante",
        "agendá a la distribuidora", "agenda a la distribuidora", "guardá la distribuidora", "guardar distribuidora"
    ]
    is_merchant_action = (
        any(k in clean_msg_lower for k in merchant_dispatch_triggers + merchant_supplier_triggers)
        or (any(w in clean_msg_lower for w in ["proveedor", "distribuidora", "viajante"]) and any(k in clean_msg_lower for k in ["agend", "anot", "guard", "telefono", "teléfono", "celular", "es el", "al "]))
    )
    if is_merchant_action:
        handled_b, reply_b, action_b = await process_boss_message(
            db=db,
            sender_phone=clean_phone,
            text=message,
            conversation_history=history
        )
        if handled_b and action_b in [
            "kiosk_order_dispatched", "basket_item_added", "single_basket_detail",
            "all_baskets_summary", "supplier_registered", "dispatch_needs_phone", "supplier_needs_phone"
        ]:
            history.append({"sender": "ai", "text": reply_b, "timestamp": datetime.now(timezone.utc).isoformat()})
            prospect.conversation_history = json.dumps(history, ensure_ascii=False)
            prospect.updated_at = datetime.now(timezone.utc)
            db.commit()
            await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=reply_b)
            return {"status": "success", "action": action_b, "reply": reply_b}

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

        safe_name = brain.sanitize_contact_first_name(prospect.contact_name)
        contact_str = f" {safe_name}" if safe_name else ""
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

    # 1.8 Multi-supplier Price Comparison Inquiry from Client (e.g. "¿Quién tiene más barato el foco LED 9W?")
    is_comparison_query = any(k in clean_msg_lower for k in [
        "mas barato", "más barato", "vende mas barato", "vende más barato",
        "tiene mas barato", "tiene más barato", "quien tiene", "quién tiene",
        "comparame", "comparar precios", "comparativa", "mejor precio",
        "quien me deja mas barato", "quién me deja más barato", "quien vende mas barato", "quién vende más barato"
    ]) and not any(k in clean_msg_lower for k in ["servicio", "software", "agencia", "abono", "ia"])

    if is_comparison_query or clean_msg_lower in ["1", "opcion 1", "opción 1", "1️⃣"]:
        safe_name = brain.sanitize_contact_first_name(prospect.contact_name)
        comp_target = message
        if clean_msg_lower in ["1", "opcion 1", "opción 1", "1️⃣"]:
            comp_target = "foco LED 9W" if "ferret" in (catalog_service.current_rubro or "").lower() else "aceite"

        formatted_comp = catalog_service.format_price_comparison(comp_target, requester_name=safe_name)
        if formatted_comp:
            history.append({"sender": "ai", "text": formatted_comp, "timestamp": datetime.now(timezone.utc).isoformat()})
            prospect.conversation_history = json.dumps(history, ensure_ascii=False)
            prospect.updated_at = datetime.now(timezone.utc)
            db.commit()

            await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=formatted_comp)
            return {
                "status": "success",
                "price_comparison": True,
                "reply": formatted_comp,
                "meeting_confirmed": False
            }

    # 1.9 Weekly Price Increases / Market Fluctuations (e.g. "¿Qué productos me aumentaron esta semana?")
    is_increase_query = any(k in clean_msg_lower for k in [
        "aumento", "aumentó", "aumentos", "aumentaron", "que aumento", "qué aumentó",
        "que productos me aumentaron", "qué productos me aumentaron", "subieron los precios",
        "variaciones de precio", "cambios de precio", "que subio", "qué subió"
    ]) and not any(k in clean_msg_lower for k in ["servicio", "software", "agencia", "abono", "ia"])

    if is_increase_query or clean_msg_lower in ["3", "opcion 3", "opción 3", "3️⃣"]:
        safe_name = brain.sanitize_contact_first_name(prospect.contact_name)
        weekly_summary = catalog_service.get_weekly_price_changes(requester_name=safe_name)
        history.append({"sender": "ai", "text": weekly_summary, "timestamp": datetime.now(timezone.utc).isoformat()})
        prospect.conversation_history = json.dumps(history, ensure_ascii=False)
        prospect.updated_at = datetime.now(timezone.utc)
        db.commit()

        await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=weekly_summary)
        return {
            "status": "success",
            "price_increases": True,
            "reply": weekly_summary,
            "meeting_confirmed": False
        }

    # 1.91 Instructions on loading/forwarding supplier catalogs (Option 4)
    if clean_msg_lower in ["4", "opcion 4", "opción 4", "4️⃣"] or (
        any(k in clean_msg_lower for k in ["cargar lista", "como cargo", "cómo cargo", "mandar lista", "enviar lista", "subir lista"])
        and not any(k in clean_msg_lower for k in ["servicio", "software", "agencia", "abono", "ia"])
    ):
        safe_name = brain.sanitize_contact_first_name(prospect.contact_name)
        greeting = f"¡Hola {safe_name}! " if safe_name else "¡Hola! "
        catalog_instructions = (
            f"{greeting}📁 *CÓMO CARGAR LISTAS DE PROVEEDORES*\n\n"
            f"Para sincronizar tus proveedores en mi memoria, solo tenés que reenviarme por este mismo chat de WhatsApp cualquier archivo en *PDF o Excel (.xlsx / .csv)* que te manden tus viajantes o distribuidores.\n\n"
            f"⚡ *En segundos:* leo las tablas, extraigo los precios actualizados y los comparo automáticamente contra tus otros distribuidores para avisarte siempre quién te deja cada artículo más barato."
        )
        history.append({"sender": "ai", "text": catalog_instructions, "timestamp": datetime.now(timezone.utc).isoformat()})
        prospect.conversation_history = json.dumps(history, ensure_ascii=False)
        prospect.updated_at = datetime.now(timezone.utc)
        db.commit()

        await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=catalog_instructions)
        return {
            "status": "success",
            "catalog_instructions": True,
            "reply": catalog_instructions,
            "meeting_confirmed": False
        }

    # 1.92 Registered Suppliers Inquiry (Option 5: e.g. "¿Qué proveedores tengo registrados?")
    is_suppliers_query = any(k in clean_msg_lower for k in [
        "que proveedores", "qué proveedores", "mis proveedores", "cuales proveedores", "cuáles proveedores",
        "proveedores registrados", "lista de proveedores", "distribuidores registrados"
    ]) and not any(k in clean_msg_lower for k in ["servicio", "software", "agencia", "abono", "ia"])

    if is_suppliers_query or clean_msg_lower in ["5", "opcion 5", "opción 5", "5️⃣"]:
        safe_name = brain.sanitize_contact_first_name(prospect.contact_name)
        sup_summary = catalog_service.get_registered_suppliers_summary(requester_name=safe_name)
        history.append({"sender": "ai", "text": sup_summary, "timestamp": datetime.now(timezone.utc).isoformat()})
        prospect.conversation_history = json.dumps(history, ensure_ascii=False)
        prospect.updated_at = datetime.now(timezone.utc)
        db.commit()

        await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=sup_summary)
        return {
            "status": "success",
            "suppliers_summary": True,
            "reply": sup_summary,
            "meeting_confirmed": False
        }

    # 1.93 Register Supplier Guidance (Option 6: e.g. "cómo agendo un proveedor" or "6")
    is_sup_reg_guide = (
        clean_msg_lower in ["6", "opcion 6", "opción 6", "6️⃣"]
        or any(k in clean_msg_lower for k in ["como agendo un proveedor", "cómo agendo un proveedor", "como cargo un proveedor", "cómo cargo un proveedor", "agregar proveedor"])
    )
    if is_sup_reg_guide:
        safe_name = brain.sanitize_contact_first_name(prospect.contact_name)
        greeting = f"¡Hola {safe_name}! " if safe_name else "¡Hola! "
        reg_guide_reply = (
            f"{greeting}🤝 *CÓMO AGENDAR PROVEEDORES NUEVOS*\n\n"
            f"Podés registrar a cualquier viajante o distribuidora de 2 formas súper fáciles:\n\n"
            f"1️⃣ *Dictámelo por audio o texto:*\n"
            f"👉 _«Sofi, agendá a Carlos de Distribuidora El Progreso al 343 453-6447»_\n\n"
            f"2️⃣ *O compartime su contacto de WhatsApp:*\n"
            f"👉 Tocás el clip 📎 ➔ *Contacto* y me lo mandás directamente.\n\n"
            f"⚡ *¿Qué hago yo al instante?* Le escribo un WhatsApp presentándome de parte tuya, le pido que me agende y le solicito su lista de precios vigente en PDF o Excel para que tengas los costos actualizados desde el día 1."
        )
        history.append({"sender": "ai", "text": reg_guide_reply, "timestamp": datetime.now(timezone.utc).isoformat()})
        prospect.conversation_history = json.dumps(history, ensure_ascii=False)
        prospect.updated_at = datetime.now(timezone.utc)
        db.commit()

        await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=reg_guide_reply)
        return {
            "status": "success",
            "supplier_reg_guide": True,
            "reply": reg_guide_reply,
            "meeting_confirmed": False
        }

    # 1.94 Client User Guide / Manual (`manual`, `guia`, `instructivo`, `modo de uso`)
    manual_triggers = ["manual", "guia", "guía", "instructivo", "modo de uso", "manual de uso", "como se usa", "cómo se usa"]
    if any(clean_msg_lower.strip() == k or clean_msg_lower.startswith(k + " ") for k in manual_triggers):
        from app.services.boss_mode import get_client_manual_text
        client_manual = get_client_manual_text()
        history.append({"sender": "ai", "text": client_manual, "timestamp": datetime.now(timezone.utc).isoformat()})
        prospect.conversation_history = json.dumps(history, ensure_ascii=False)
        prospect.updated_at = datetime.now(timezone.utc)
        db.commit()

        await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=client_manual)
        return {
            "status": "success",
            "client_manual_sent": True,
            "reply": client_manual,
            "meeting_confirmed": False
        }

    # 1.95 Guided Menu Repetition for newly onboarded client greeting
    if prospect.campaign == "client_onboarding" and clean_msg_lower in [
        "hola", "buenas", "buen dia", "buen día", "buenas tardes", "hola sofi", "hola sofia", "menu", "menú", "ayuda", "?"
    ]:
        safe_name = brain.sanitize_contact_first_name(prospect.contact_name) or "amigo"
        b_name = prospect.name or "tu negocio"
        is_ferret = "ferret" in (catalog_service.current_rubro or "").lower()
        if is_ferret:
            menu_reply = (
                f"¡Hola {safe_name}! 👋 Soy Sofía, tu asistente de compras en *{b_name}*.\n"
                f"Activé un catálogo de demostración con distribuidores de ferretería para que hagamos una prueba en vivo juntos.\n\n"
                f"🎯 *Podés mandarme un audio o texto probando cualquiera de estas opciones:*\n\n"
                f"1️⃣ _«Sofi, ¿quién tiene más barato el foco LED 9W?»_\n"
                f"2️⃣ _«Anotame 10 cajas de tornillos y 2 pinzas»_\n"
                f"3️⃣ _«¿Qué productos me aumentaron esta semana?»_\n"
                f"4️⃣ _Reenviame una lista de precios en PDF o Excel de cualquier distribuidor para guardarla en mi memoria_\n"
                f"5️⃣ _«¿Qué proveedores tengo registrados?»_\n"
                f"6️⃣ _«Sofi, agendá a Carlos de Distribuidora El Progreso al 343...» (o compartime su contacto)_ 🆕\n\n"
                f"¿Qué querés que revisemos primero?"
            )
        else:
            menu_reply = (
                f"¡Hola {safe_name}! 👋 Soy Sofía, tu asistente de compras en *{b_name}*.\n"
                f"Activé un catálogo de demostración con distribuidores mayoristas de alimentos para que hagamos una prueba en vivo juntos.\n\n"
                f"🎯 *Podés mandarme un audio o texto probando cualquiera de estas opciones:*\n\n"
                f"1️⃣ _«Sofi, ¿quién tiene más barato el aceite?»_\n"
                f"2️⃣ _«Anotame un pedido de 10 paquetes de harina y 5 aceites»_\n"
                f"3️⃣ _«¿Qué productos me aumentaron esta semana?»_\n"
                f"4️⃣ _Reenviame una lista de precios en PDF o Excel de cualquier distribuidor para guardarla en mi memoria_\n"
                f"5️⃣ _«¿Qué proveedores tengo registrados?»_\n"
                f"6️⃣ _«Sofi, agendá a Carlos de Molinos al 343...» (o compartime su contacto)_ 🆕\n\n"
                f"¿Qué querés que revisemos primero?"
            )
        history.append({"sender": "ai", "text": menu_reply, "timestamp": datetime.now(timezone.utc).isoformat()})
        prospect.conversation_history = json.dumps(history, ensure_ascii=False)
        prospect.updated_at = datetime.now(timezone.utc)
        db.commit()

        await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=menu_reply)
        return {
            "status": "success",
            "guided_menu": True,
            "reply": menu_reply,
            "meeting_confirmed": False
        }

    # 2. Check if customer wants to place a new order or consult product/stock
    analysis = await parse_order_or_inquiry_with_ai(message)
    if analysis.intent == "order":
        if analysis.draft.items:
            order_summary = format_order_summary_message(analysis.draft, prospect.contact_name)
            prospect.notes = json.dumps({
                "type": "PEDIDO_PENDIENTE",
                "items": [
                    {"name": it.product.name, "presentation": it.product.presentation, "qty": it.quantity, "subtotal": it.subtotal}
                    for it in analysis.draft.items if it.in_stock
                ],
                "total": analysis.draft.total,
                "total_str": analysis.draft.formatted_total()
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
        elif analysis.draft.unmatched_queries:
            unmatched_str = ", ".join(f"*{q}*" for q in analysis.draft.unmatched_queries)
            unmatched_reply = (
                f"¡Hola! Disculpá, pero actualmente no trabajamos {unmatched_str} en nuestro catálogo de distribución "
                f"(manejamos líneas de alimentos, bebidas, lácteos y artículos de almacén).\n\n"
                f"💡 Si querés ver todos los artículos que tenemos disponibles para el reparto, "
                f"escribime 'mandame la lista' o consultame por productos puntuales."
            )
            history.append({"sender": "ai", "text": unmatched_reply, "timestamp": datetime.now(timezone.utc).isoformat()})
            prospect.conversation_history = json.dumps(history, ensure_ascii=False)
            prospect.updated_at = datetime.now(timezone.utc)
            db.commit()

            await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=unmatched_reply)
            return {
                "status": "success",
                "order_unmatched": True,
                "reply": unmatched_reply,
                "meeting_confirmed": False
            }
    elif analysis.intent == "product_inquiry":
        found_prods = [catalog_service.find_product_exact_or_best(q) for q in analysis.inquired_products]
        is_quote = any(p is not None for p in found_prods)
        inquiry_reply = build_product_inquiry_reply(analysis.inquired_products, contact_name=prospect.contact_name)
        history.append({"sender": "ai", "text": inquiry_reply, "timestamp": datetime.now(timezone.utc).isoformat()})
        prospect.conversation_history = json.dumps(history, ensure_ascii=False)
        prospect.updated_at = datetime.now(timezone.utc)
        db.commit()

        await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=inquiry_reply)
        return {
            "status": "success",
            "product_inquiry": True,
            "price_quote": is_quote,
            "reply": inquiry_reply,
            "meeting_confirmed": False
        }

    # 2.5 Check if customer asks for the full price list / catalog / Excel
    price_list_triggers = [
        "lista de precio", "lista de precios", "lista actualizada", "pasame la lista", 
        "mandame la lista", "pasanos la lista", "ver la lista", "catalogo", "catálogo", 
        "tienen lista", "tenes lista", "tenés lista", "mandame los precios", "pasame los precios",
        "precios actualizados", "que precios tenes", "qué precios tenés", "el excel", "mandame el excel",
        "pasame el excel", "tu excel", "la planilla",
        "lista completa", "lista de precios completa", "mandame la lista completa", "pasame la lista completa",
        "catalogo completo", "catálogo completo", "el catalogo", "el catálogo", "la lista", "lista entera",
        "todos los precios", "enviame la lista", "enviar la lista", "pasar la lista", "mandame el catalogo",
        "pasame el catalogo", "mandame el catálogo", "pasame el catálogo",
        # Brazilian Portuguese triggers
        "tabela de preço", "tabela de preços", "tabela de precos", "manda a tabela",
        "manda a lista", "passa a tabela", "tem tabela", "ver tabela"
    ]
    if (any(trigger in message.lower() for trigger in price_list_triggers) or analysis.intent == "price_list_request") and catalog_service.products:
        if not any(k in message.lower() for k in ["servicio", "software", "agencia", "abono", "ia"]):
            # Extract name if prospect introduced themselves (e.g. "soy Martin del kiosco..." or "sou a Mariana...")
            soy_match = re.search(r'\b(?:soy|me llamo|te habla|habla|sou|me chamo)\s+([a-zA-ZáéíóúÁÉÍÓÚñÑãõÃÕ]{3,15})\b', message, re.IGNORECASE)
            if soy_match:
                extracted_name = soy_match.group(1).capitalize()
                prospect.contact_name = extracted_name

            safe_name = brain.sanitize_contact_first_name(prospect.contact_name)
            
            if brain.is_portuguese_interaction(message, clean_phone):
                contact_greeting = f"Oi {safe_name}! Tudo bem?" if safe_name else "Oi! Tudo bem?"
                price_list_reply = (
                    f"{contact_greeting} Segue aqui em anexo a nossa tabela de preços completa "
                    f"e atualizada em Excel para você conferir no celular ou no computador.\n\n"
                    f"📦 *Condições gerais:*\n"
                    f"• Pedidos anotados e despachados direto pro estoque.\n"
                    f"• Atendimento 24/7 com pronta-entrega.\n\n"
                    f"💡 Se preferir consultar o valor de algum item específico ou já fechar um pedido, "
                    f"é só me mandar mensagem ou áudio direto por aqui!"
                )
            else:
                contact_greeting = f"¡Hola {safe_name}! ¿Cómo estás?" if safe_name else "¡Hola! ¿Cómo estás?"
                price_list_reply = (
                    f"{contact_greeting} Te adjunto acá mismo el archivo de Excel con nuestra lista de precios "
                    f"completa y actualizada al día de hoy para que la mires tranquilo en el celu o la compu.\n\n"
                    f"📦 *Condiciones vigentes:*\n"
                    f"• Reparto con flete sin cargo a partir de $50.000.\n"
                    f"• Tomamos pedidos hasta las 21:00 hs para salir en el reparto de mañana.\n\n"
                    f"💡 Si preferís consultarme el precio de algún artículo puntual o armar tu pedido, "
                    f"escribime o mandame un audio directo por acá y te lo anoto en el acto."
                )

            history.append({"sender": "ai", "text": price_list_reply, "timestamp": datetime.now(timezone.utc).isoformat()})
            prospect.conversation_history = json.dumps(history, ensure_ascii=False)
            prospect.updated_at = datetime.now(timezone.utc)
            db.commit()

            # 1. Send explanatory WhatsApp text
            await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=price_list_reply)

            # 2. Attach the actual .xlsx Excel file to WhatsApp chat
            excel_url = "https://sofia-ai-agency.onrender.com/assets/catalogo_actualizado.xlsx"
            asyncio.create_task(whatsapp.send_whatsapp_document(
                to_phone=clean_phone,
                document_url=excel_url,
                filename="Lista_Precios_Distribuidora.xlsx",
                caption="📊 Lista de Precios Oficial Actualizada"
            ))

            return {
                "status": "success",
                "price_list_sent": True,
                "reply": price_list_reply,
                "excel_sent": True,
                "meeting_confirmed": False
            }

    # 3. Check if customer asks about a specific product's price
    if any(k in message.lower() for k in ["cuanto", "cuánto", "precio", "sale", "tenes", "tenés", "a cuanto", "a cuánto"]) and catalog_service.products:
        if not any(k in message.lower() for k in ["servicio", "software", "agencia", "sofia", "ia", "abono"]):
            found_prod = catalog_service.find_product_exact_or_best(message)
            if found_prod:
                stock_info = "tenemos stock disponible" if found_prod.in_stock else "actualmente figura sin stock"
                safe_name = brain.sanitize_contact_first_name(prospect.contact_name)
                contact_str = f" {safe_name}" if safe_name else ""
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

    # 4. Check if lead is explicitly requesting the demo video (from template CTA)
    clean_lower = message.strip().lower()
    is_demo_intent = False
    if clean_lower in [
        "demo", "la demo", "ver demo", "quiero demo", "quiero la demo",
        "video", "video demo", "el video", "mandame el video", "mandá el video",
        "pasame el video", "pasanos el video", "pasame la demo", "mandame la demo",
        "ver demostración", "ver demostracion", "demostración", "demostracion",
        "ver la demostración", "ver la demostracion", "quiero ver una demostración",
        "quiero ver una demostracion", "me gustaría ver una demostración", "me gustaria ver una demostracion"
    ] or "video demo" in clean_lower or "ver demo" in clean_lower or "ver demostra" in clean_lower:
        is_demo_intent = True
    elif any(phrase in clean_lower for phrase in [
        "mandame el video", "mandá el video", "pasame el video", "pasanos el video",
        "mandame la demo", "pasame la demo", "ver demostración", "ver demostracion"
    ]):
        is_demo_intent = True

    if is_demo_intent:
        prospect.status = "demo_requested"
        safe_name = brain.sanitize_contact_first_name(prospect.contact_name)
        contact_str = f" {safe_name}" if safe_name else ""
        demo_reply = (
            f"¡Hola{contact_str}! Qué bueno que te interese ver cómo funciona Sofía. "
            f"En breve nuestro asesor te va a enviar el video demo para que veas el sistema en acción. "
            f"¡Muchas gracias por escribirme!"
        )
        history.append({"sender": "ai", "text": demo_reply, "timestamp": datetime.now(timezone.utc).isoformat()})
        prospect.conversation_history = json.dumps(history, ensure_ascii=False)
        prospect.updated_at = datetime.now(timezone.utc)
        db.commit()

        asyncio.create_task(whatsapp.notify_owner_demo_requested(
            client_name=prospect.name,
            contact_name=prospect.contact_name,
            phone=clean_phone,
            incoming_text=message
        ))

        await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=demo_reply)
        return {
            "status": "success",
            "demo_requested": True,
            "reply": demo_reply,
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
        campaign=prospect.campaign or "ai_agency",
        phone=clean_phone
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

    # If incoming message was voice or from test phone, also send response as voice audio!
    if getattr(settings, "ENABLE_VOICE_RESPONSES", False) and (is_incoming_voice or clean_phone in ["5493434536447", "543434536447"]):
        try:
            from app.services.voice import text_to_speech_bytes
            audio_bytes = await text_to_speech_bytes(ai_response)
            if audio_bytes:
                await whatsapp.send_whatsapp_audio(to_phone=clean_phone, audio_bytes=audio_bytes)
                logger.info(f"🎙️ Sent voice response audio to {clean_phone}")
        except Exception as v_err:
            logger.error(f"Error generating or sending voice response: {v_err}")

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
