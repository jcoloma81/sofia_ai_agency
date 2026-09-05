import re
import json
import base64
import logging
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

        # Text extraction (if not voice note)
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

    # Remote reactivation check from Javier's personal alert phone
    if clean_phone == settings.WHATSAPP_ALERT_PHONE:
        lower_msg = message.lower().strip()
        if lower_msg.startswith("activar") or lower_msg.startswith("reactivar"):
            num_matches = re.findall(r'\d+', lower_msg)
            if num_matches:
                target_number = num_matches[-1]
                target_lead = db.query(Prospect).filter(Prospect.phone.like(f"%{target_number}%")).first()
                if target_lead:
                    target_lead.status = "in_conversation"
                    db.commit()
                    await whatsapp.send_whatsapp_message(
                        to_phone=clean_phone,
                        text=f"✅ Listo Javier, reactivé la atención de Sofía para {target_lead.name} ({target_lead.phone})."
                    )
                    return {"status": "success", "action": "lead_reactivated"}

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
        await whatsapp.notify_javier_meeting_scheduled(
            prospect_name=prospect.name,
            contact_name=prospect.contact_name,
            phone=prospect.phone,
            city=prospect.city,
            meeting_details=prospect.meeting_details,
            last_message=message.strip(),
            campaign=prospect.campaign or "ai_agency"
        )
    else:
        if prospect.status == "pending":
            prospect.status = "in_conversation"
        db.commit()
        db.refresh(prospect)

    # Send response back to prospect via WhatsApp
    await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=ai_response)

    return {
        "status": "success",
        "reply": ai_response,
        "meeting_confirmed": is_meeting_confirmed,
        "meeting_details": meeting_details
    }
