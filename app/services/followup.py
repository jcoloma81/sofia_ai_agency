import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session
from app.models.prospect import Prospect
from app.services import whatsapp
from app.config.settings import settings

logger = logging.getLogger(__name__)

FOLLOWUP_1_MIN_HOURS = 24  # Wait at least 24hs for first follow-up
FOLLOWUP_2_MIN_HOURS = 72  # Wait at least 72hs for break-up message

async def check_and_send_followups(db: Session, dry_run: bool = False) -> Dict[str, Any]:
    """
    Scans prospects in 'contacted' status whose last message is from Sofia and where no
    reply was received within the follow-up threshold.
    
    Sequence:
    - Step 1 (24-48hs): Cordial reminder.
    - Step 2 (72-96hs): Respectful closing/breakup message leaving door open.
    """
    now = datetime.now(timezone.utc)
    candidates = db.query(Prospect).filter(
        Prospect.status.in_(["contacted", "in_conversation"])
    ).all()

    processed = []

    for prospect in candidates:
        try:
            history = json.loads(prospect.conversation_history or "[]")
        except Exception:
            history = []

        if not history:
            continue

        last_msg = history[-1]
        sender = last_msg.get("sender")
        raw_ts = last_msg.get("timestamp")

        # If last sender is prospect or human takeover, do NOT send follow-up
        if sender in ["prospect", "javier_human"] or prospect.status == "human_takeover":
            continue

        # Parse timestamp
        if not raw_ts:
            continue

        try:
            msg_time = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        except Exception:
            continue

        hours_elapsed = (now - msg_time).total_seconds() / 3600.0

        target_followup = None
        followup_type = None

        # Determine which follow-up is due
        has_sent_fu1 = any(m.get("sender") == "ai_followup_1" for m in history)
        has_sent_fu2 = any(m.get("sender") == "ai_followup_2" for m in history)

        from app.services.brain import sanitize_contact_first_name
        safe_name = sanitize_contact_first_name(prospect.contact_name)
        contact_label = f" {safe_name}" if safe_name else ""
        empresa_label = f" en {prospect.name}" if prospect.name and not safe_name else ""

        if not has_sent_fu1 and hours_elapsed >= FOLLOWUP_1_MIN_HOURS:
            followup_type = "ai_followup_1"
            target_followup = (
                f"¡Hola{contact_label}! ¿Cómo estás? Te consulto por las dudas para no ser insistente, "
                f"¿pudiste ver el mensajito que te dejé sobre la automatización comercial con IA{empresa_label}? "
                f"Cualquier duda avisame por acá. ¡Que tengas un gran día!"
            )
        elif has_sent_fu1 and not has_sent_fu2 and hours_elapsed >= FOLLOWUP_2_MIN_HOURS:
            followup_type = "ai_followup_2"
            target_followup = (
                f"¡Hola{contact_label}! Asumo que deben estar a mil con el trabajo y no es el momento oportuno. "
                f"Te dejo nuestro contacto guardado por acá por si más adelante les interesa sumar IA y acelerar las ventas de la empresa. "
                f"¡Muchos éxitos!"
            )

        if target_followup:
            action_record = {
                "prospect_id": prospect.id,
                "name": prospect.name,
                "phone": prospect.phone,
                "followup_type": followup_type,
                "hours_elapsed": round(hours_elapsed, 1),
                "message": target_followup,
                "dry_run": dry_run
            }

            if not dry_run:
                sent = await whatsapp.send_whatsapp_message(to_phone=prospect.phone, text=target_followup)
                history.append({
                    "sender": followup_type,
                    "text": target_followup,
                    "timestamp": now.isoformat()
                })
                prospect.conversation_history = json.dumps(history, ensure_ascii=False)
                if followup_type == "ai_followup_2":
                    prospect.status = "not_interested"
                prospect.updated_at = now
                db.commit()
                action_record["sent"] = sent
            else:
                action_record["sent"] = False

            processed.append(action_record)

    logger.info(f"Follow-up processor executed: {len(processed)} prospects acted on (dry_run={dry_run}).")
    return {
        "status": "success",
        "processed_count": len(processed),
        "actions": processed
    }
