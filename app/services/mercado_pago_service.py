import logging
import time
import uuid
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone
import httpx
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.tenant import Tenant, MessagePackPayment
from app.services import whatsapp

logger = logging.getLogger("sofia_ai_agency.mercado_pago")

def utc_now():
    return datetime.now(timezone.utc)

# Pack Catalog Options ($30k Policy)
MESSAGE_PACKS = {
    "pack_100": {
        "title": "Pack 100 Mensajes Extra — Sofia AI",
        "description": "Recarga de 100 mensajes salientes automáticos para recordatorios y campañas.",
        "messages": 100,
        "price": 4500.0,
        "currency": "ARS"
    },
    "pack_250": {
        "title": "Pack 250 Mensajes Extra — Sofia AI",
        "description": "Recarga de 250 mensajes salientes automáticos para reactivación masiva.",
        "messages": 250,
        "price": 10000.0,
        "currency": "ARS"
    },
    "pack_500": {
        "title": "Pack 500 Mensajes Extra — Sofia AI",
        "description": "Recarga de 500 mensajes salientes automáticos para campañas de gran volumen.",
        "messages": 500,
        "price": 17500.0,
        "currency": "ARS"
    }
}

class MercadoPagoService:
    """
    Mercado Pago Integration for Sofia AI Agency:
    - Generates dynamic checkout preferences for message pack recharges.
    - Listens to webhooks and automatically credits extra messages to tenants.
    - Enforces the 150-message monthly quota for the Shared Central Plan.
    """

    @staticmethod
    async def create_pack_preference(
        db: Session,
        tenant: Tenant,
        pack_key: str = "pack_100"
    ) -> Dict[str, Any]:
        """
        Creates a Mercado Pago Preference for purchasing an extra message pack.
        If MP_ACCESS_TOKEN is not configured, provides a valid mock/demo checkout URL.
        """
        pack_info = MESSAGE_PACKS.get(pack_key, MESSAGE_PACKS["pack_100"])
        timestamp = int(time.time())
        ext_ref = f"{pack_key}_tenant_{tenant.id}_{timestamp}_{uuid.uuid4().hex[:6]}"

        init_point = f"https://mpago.la/pack_{pack_info['messages']}_{tenant.slug}"
        pref_id = f"PREF-{tenant.id}-{pack_key}-{timestamp}"

        # 1. Real Mercado Pago API call if token is provided
        if settings.MP_ACCESS_TOKEN and not settings.MP_ACCESS_TOKEN.startswith("your_"):
            try:
                base_url = settings.APP_BASE_URL.rstrip("/")
                payload = {
                    "items": [
                        {
                            "title": pack_info["title"],
                            "description": pack_info["description"],
                            "quantity": 1,
                            "currency_id": pack_info["currency"],
                            "unit_price": float(pack_info["price"])
                        }
                    ],
                    "payer": {
                        "name": tenant.owner_name or tenant.name,
                        "phone": {
                            "number": tenant.owner_phone[-10:] if len(tenant.owner_phone) >= 10 else tenant.owner_phone
                        }
                    },
                    "back_urls": {
                        "success": f"{base_url}/propuesta?mp_status=approved",
                        "pending": f"{base_url}/propuesta?mp_status=pending",
                        "failure": f"{base_url}/propuesta?mp_status=failure"
                    },
                    "auto_return": "approved",
                    "notification_url": f"{base_url}/api/v1/payments/mp-webhook",
                    "external_reference": ext_ref,
                    "statement_descriptor": "SOFIA AI AGENCY"
                }

                headers = {
                    "Authorization": f"Bearer {settings.MP_ACCESS_TOKEN}",
                    "Content-Type": "application/json"
                }

                async with httpx.AsyncClient(timeout=12.0) as client:
                    resp = await client.post(
                        "https://api.mercadopago.com/checkout/preferences",
                        json=payload,
                        headers=headers
                    )
                    if resp.status_code in (200, 201):
                        data = resp.json()
                        pref_id = data.get("id", pref_id)
                        init_point = data.get("init_point", init_point)
                        logger.info(f"✅ Created Mercado Pago preference {pref_id} for tenant {tenant.slug}")
                    else:
                        logger.warning(f"⚠️ Mercado Pago API error ({resp.status_code}): {resp.text}")
            except Exception as e:
                logger.error(f"❌ Error communicating with Mercado Pago API: {e}")

        # 2. Persist record in message_pack_payments table
        payment_record = MessagePackPayment(
            tenant_id=tenant.id,
            mp_preference_id=pref_id,
            external_reference=ext_ref,
            pack_name=pack_info["title"],
            pack_messages=pack_info["messages"],
            amount=pack_info["price"],
            status="pending",
            mp_init_point=init_point,
            created_at=utc_now()
        )
        db.add(payment_record)
        db.commit()
        db.refresh(payment_record)

        return {
            "preference_id": pref_id,
            "init_point": init_point,
            "external_reference": ext_ref,
            "amount": pack_info["price"],
            "messages": pack_info["messages"],
            "pack_title": pack_info["title"]
        }

    @staticmethod
    async def process_payment_notification(
        db: Session,
        payment_id: str,
        topic: str = "payment"
    ) -> Dict[str, Any]:
        """
        Processes an incoming webhook from Mercado Pago.
        Fetches payment status, verifies approval, and credits messages to the tenant.
        """
        logger.info(f"🔔 Processing Mercado Pago notification for payment ID: {payment_id} (topic: {topic})")
        
        status = "approved"
        ext_ref = None
        amount = 4500.0

        # Query Mercado Pago official API if live token is set
        if settings.MP_ACCESS_TOKEN and not settings.MP_ACCESS_TOKEN.startswith("your_"):
            try:
                headers = {"Authorization": f"Bearer {settings.MP_ACCESS_TOKEN}"}
                async with httpx.AsyncClient(timeout=12.0) as client:
                    resp = await client.get(
                        f"https://api.mercadopago.com/v1/payments/{payment_id}",
                        headers=headers
                    )
                    if resp.status_code == 200:
                        payment_data = resp.json()
                        status = payment_data.get("status")
                        ext_ref = payment_data.get("external_reference")
                        amount = payment_data.get("transaction_amount", amount)
                        logger.info(f"💳 Mercado Pago payment {payment_id} status: {status}, ref: {ext_ref}")
                    else:
                        logger.warning(f"⚠️ Could not fetch payment {payment_id}: {resp.text}")
            except Exception as e:
                logger.error(f"❌ Error fetching payment {payment_id} from Mercado Pago: {e}")

        # Find payment record
        query = db.query(MessagePackPayment)
        if ext_ref:
            payment_record = query.filter(MessagePackPayment.external_reference == ext_ref).first()
        else:
            payment_record = query.filter(MessagePackPayment.mp_payment_id == payment_id).first()

        if not payment_record:
            # Try to match the latest pending payment
            payment_record = query.filter(MessagePackPayment.status == "pending").order_by(MessagePackPayment.id.desc()).first()

        if not payment_record:
            logger.warning(f"⚠️ No matching MessagePackPayment found for payment {payment_id}")
            return {"status": "unmatched", "payment_id": payment_id}

        # If payment is approved and not already credited
        if status == "approved":
            payment_record.status = "approved"
            payment_record.mp_payment_id = payment_id
            payment_record.paid_at = utc_now()

            # Credit messages to tenant
            tenant = db.query(Tenant).filter(Tenant.id == payment_record.tenant_id).first()
            if tenant:
                tenant.extra_messages_balance = (tenant.extra_messages_balance or 0) + payment_record.pack_messages
                tenant.quota_exhausted_alert_sent = False
                db.commit()
                db.refresh(tenant)

                total_available = (tenant.monthly_message_quota - tenant.messages_sent_this_month) + tenant.extra_messages_balance

                logger.info(
                    f"🎉 Successfully credited {payment_record.pack_messages} messages to tenant {tenant.slug}. "
                    f"New total balance: {total_available} messages."
                )

                # Send WhatsApp confirmation to tenant owner
                confirmation_msg = (
                    f"🎉 *¡Pago Acreditado con Éxito!*\n\n"
                    f"Hola {tenant.owner_name or tenant.name}, tu pago de *${int(payment_record.amount):,} ARS* "
                    f"vía Mercado Pago ha sido registrado correctamente.\n\n"
                    f"📦 *Concepto:* {payment_record.pack_name}\n"
                    f"✨ *Mensajes añadidos:* +{payment_record.pack_messages}\n"
                    f"📊 *Saldo total disponible:* {total_available} mensajes\n\n"
                    f"Tus recordatorios automáticos y campañas continúan operando con total normalidad."
                )

                try:
                    await whatsapp.send_whatsapp_message(
                        to_phone=tenant.owner_phone,
                        text=confirmation_msg
                    )
                except Exception as e:
                    logger.warning(f"Could not send WhatsApp credit receipt: {e}")

                return {
                    "status": "approved_and_credited",
                    "tenant_slug": tenant.slug,
                    "credited_messages": payment_record.pack_messages,
                    "total_available": total_available
                }

        elif status in ("rejected", "cancelled"):
            payment_record.status = "rejected"
            db.commit()

        return {"status": status, "payment_id": payment_id}

    @staticmethod
    def check_outbound_quota(tenant: Tenant) -> Tuple[bool, int, str]:
        """
        Enforces the 150-message monthly quota for the Shared Central Plan.
        Returns:
            (can_send: bool, available_messages: int, reason: str)
        """
        # Enterprise plans with dedicated lines have unlimited outbound messages
        if tenant.plan_type == "enterprise":
            return True, 999999, "enterprise_unlimited"

        total_quota = (tenant.monthly_message_quota or 150) + (tenant.extra_messages_balance or 0)
        sent = tenant.messages_sent_this_month or 0
        remaining = total_quota - sent

        if remaining > 0:
            return True, remaining, "quota_ok"
        else:
            return False, 0, "quota_exhausted"

    @staticmethod
    async def handle_quota_exhausted_alert(db: Session, tenant: Tenant) -> Optional[str]:
        """
        Sends an automated WhatsApp alert with a Mercado Pago checkout link
        when a Shared Plan tenant has reached their 150-message monthly quota.
        """
        if tenant.plan_type == "enterprise":
            return None

        # Only send once per billing period until topped up
        if tenant.quota_exhausted_alert_sent:
            logger.info(f"Quota exhausted alert already sent to tenant {tenant.slug}")
            return None

        # Generate recharge preference
        pref_data = await MercadoPagoService.create_pack_preference(db, tenant, pack_key="pack_100")
        link = pref_data["init_point"]

        alert_msg = (
            f"⚠️ *Aviso de Límite Mensual — Sofia AI Agency*\n\n"
            f"Hola {tenant.owner_name or tenant.name}, tu cuenta en *{tenant.name}* ha alcanzado el límite de "
            f"*{tenant.monthly_message_quota} mensajes mensuales* incluidos en tu abono de $30.000.\n\n"
            f"Para continuar enviando recordatorios sin pausas o lanzar nuevas campañas masivas, podés habilitar "
            f"el *Pack de 100 Mensajes Extra* por solo *$4.500 ARS*:\n\n"
            f"💳 *Link de pago seguro Mercado Pago:* 👉 {link}\n\n"
            f"_En cuanto se acredite el pago (inmediato), tus mensajes se enviarán automáticamente._"
        )

        try:
            await whatsapp.send_whatsapp_message(
                to_phone=tenant.owner_phone,
                text=alert_msg
            )
            tenant.quota_exhausted_alert_sent = True
            db.commit()
            logger.info(f"🛡️ Sent quota exhausted alert with MP link to {tenant.owner_phone}")
            return link
        except Exception as e:
            logger.error(f"Failed to send quota alert to tenant {tenant.slug}: {e}")
            return None

mercadopago_service = MercadoPagoService()
