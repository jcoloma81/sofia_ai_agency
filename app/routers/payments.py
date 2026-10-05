import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Request, Query, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.services.mercado_pago_service import mercadopago_service, MESSAGE_PACKS

logger = logging.getLogger("sofia_ai_agency.payments_router")

router = APIRouter(prefix="/api/v1/payments", tags=["Mercado Pago Billing & Message Packs"])

@router.post("/mp-webhook")
@router.get("/mp-webhook")
async def mercado_pago_webhook(
    request: Request,
    db: Session = Depends(get_db),
    topic: Optional[str] = Query(None),
    id: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    data_id: Optional[str] = Query(None, alias="data.id")
):
    """
    Mercado Pago IPN & Webhook Receiver:
    Accepts both JSON POST payloads and GET query parameter notifications.
    Automatically credits purchased message packs when payment is approved.
    """
    payment_id = id or data_id
    notification_topic = topic or type or "payment"

    # If it's a POST request with JSON body
    if request.method == "POST":
        try:
            body = await request.json()
            if isinstance(body, dict):
                payment_id = payment_id or body.get("data", {}).get("id") or body.get("id")
                notification_topic = notification_topic or body.get("type") or body.get("action")
        except Exception:
            pass

    logger.info(f"📨 Inbound MP webhook: topic={notification_topic}, payment_id={payment_id}")

    if not payment_id:
        return JSONResponse(status_code=200, content={"status": "received", "note": "no payment id provided"})

    # Process and credit
    result = await mercadopago_service.process_payment_notification(
        db=db,
        payment_id=str(payment_id),
        topic=str(notification_topic)
    )

    return JSONResponse(status_code=200, content={"status": "ok", "result": result})

@router.post("/create-pack-preference")
async def create_pack_preference(
    tenant_slug: str,
    pack_key: str = "pack_100",
    db: Session = Depends(get_db)
):
    """
    Generates a dynamic Mercado Pago checkout link for a tenant to purchase a message pack.
    """
    tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found"
        )

    if pack_key not in MESSAGE_PACKS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid pack_key '{pack_key}'. Available: {list(MESSAGE_PACKS.keys())}"
        )

    pref_data = await mercadopago_service.create_pack_preference(
        db=db,
        tenant=tenant,
        pack_key=pack_key
    )

    return {
        "status": "success",
        "tenant_slug": tenant.slug,
        "preference": pref_data
    }

@router.get("/quota/{tenant_slug}")
def get_tenant_quota(
    tenant_slug: str,
    db: Session = Depends(get_db)
):
    """
    Returns current message quota, sent messages, extra balance, and available remaining messages.
    """
    tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found"
        )

    can_send, remaining, reason = mercadopago_service.check_outbound_quota(tenant)

    return {
        "tenant_slug": tenant.slug,
        "plan_type": tenant.plan_type,
        "monthly_quota": tenant.monthly_message_quota,
        "messages_sent_this_month": tenant.messages_sent_this_month,
        "extra_messages_balance": tenant.extra_messages_balance,
        "remaining_messages": remaining,
        "can_send": can_send,
        "status_reason": reason
    }
