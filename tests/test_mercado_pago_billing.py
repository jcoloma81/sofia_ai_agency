import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from main import app
from tests.conftest import TestingSessionLocal
from app.models.tenant import Tenant, MessagePackPayment
from app.services.mercado_pago_service import mercadopago_service

client = TestClient(app)

def test_mercado_pago_quota_and_billing_lifecycle():
    db = TestingSessionLocal()
    try:
        # 1. Create a Shared Plan Tenant (150 msgs quota)
        slug = f"test_gym_{int(datetime.now(timezone.utc).timestamp())}"
        tenant = Tenant(
            slug=slug,
            name="Test Gym Paraná",
            business_type="gimnasio",
            owner_phone="5493434536447",
            owner_name="Lucas Dueño",
            plan_type="shared",
            monthly_message_quota=150,
            messages_sent_this_month=0,
            extra_messages_balance=0,
            quota_exhausted_alert_sent=False
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        # 2. Check initial quota: 150 available
        can_send, remaining, reason = mercadopago_service.check_outbound_quota(tenant)
        assert can_send is True
        assert remaining == 150
        assert reason == "quota_ok"

        # 3. Exhaust quota: set messages_sent_this_month = 150
        tenant.messages_sent_this_month = 150
        db.commit()
        db.refresh(tenant)

        can_send, remaining, reason = mercadopago_service.check_outbound_quota(tenant)
        assert can_send is False
        assert remaining == 0
        assert reason == "quota_exhausted"

        # 4. Trigger Quota Alert (Sends WhatsApp alert to owner with MP link)
        import asyncio
        with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            link = asyncio.run(mercadopago_service.handle_quota_exhausted_alert(db, tenant))
            assert link is not None
            assert tenant.quota_exhausted_alert_sent is True

        # 5. Create a Pack Preference via API
        res_pref = client.post(
            "/api/v1/payments/create-pack-preference",
            params={"tenant_slug": slug, "pack_key": "pack_100"}
        )
        assert res_pref.status_code == 200
        pref_json = res_pref.json()
        assert pref_json["status"] == "success"
        ext_ref = pref_json["preference"]["external_reference"]
        assert "pack_100" in ext_ref

        # Verify DB pending payment record
        pay_rec = db.query(MessagePackPayment).filter(MessagePackPayment.external_reference == ext_ref).first()
        assert pay_rec is not None
        assert pay_rec.status == "pending"
        assert pay_rec.pack_messages == 100
        assert pay_rec.amount == 4500.0

        # 6. Simulate Mercado Pago Webhook with approved payment
        with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_wa:
            mock_wa.return_value = True
            res_wh = client.post(
                "/api/v1/payments/mp-webhook",
                json={
                    "action": "payment.created",
                    "type": "payment",
                    "data": {"id": "12345678901"}
                }
            )
            assert res_wh.status_code == 200

        # Verify messages are now credited (+100 extra messages!)
        db.refresh(tenant)
        assert tenant.extra_messages_balance == 100

        # Check quota is now OK again! (100 remaining)
        can_send, remaining, reason = mercadopago_service.check_outbound_quota(tenant)
        assert can_send is True
        assert remaining == 100

        # 7. Check /api/v1/payments/quota/{tenant_slug} endpoint
        res_quota = client.get(f"/api/v1/payments/quota/{slug}")
        assert res_quota.status_code == 200
        q_data = res_quota.json()
        assert q_data["plan_type"] == "shared"
        assert q_data["monthly_quota"] == 150
        assert q_data["messages_sent_this_month"] == 150
        assert q_data["extra_messages_balance"] == 100
        assert q_data["remaining_messages"] == 100
        assert q_data["can_send"] is True

        # Clean up
        db.delete(tenant)
        db.commit()

    finally:
        db.close()

def test_enterprise_plan_has_unlimited_quota():
    db = TestingSessionLocal()
    try:
        slug = f"test_ent_{int(datetime.now(timezone.utc).timestamp())}"
        tenant = Tenant(
            slug=slug,
            name="Sanatorio Central",
            business_type="salud",
            owner_phone="5493434536447",
            plan_type="enterprise",
            monthly_message_quota=999999,
            messages_sent_this_month=5000
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        can_send, remaining, reason = mercadopago_service.check_outbound_quota(tenant)
        assert can_send is True
        assert remaining == 999999
        assert reason == "enterprise_unlimited"

        db.delete(tenant)
        db.commit()
    finally:
        db.close()


def test_monthly_quota_reset_lifecycle():
    db = TestingSessionLocal()
    try:
        # Create a shared tenant with quota exhausted in previous month
        slug = f"test_reset_{int(datetime.now(timezone.utc).timestamp())}"
        past_date = datetime(2026, 1, 15, tzinfo=timezone.utc)
        tenant = Tenant(
            slug=slug,
            name="Past Month Gym",
            business_type="gimnasio",
            owner_phone="5493434536447",
            plan_type="shared",
            monthly_message_quota=150,
            messages_sent_this_month=150,
            extra_messages_balance=25,
            quota_exhausted_alert_sent=True,
            last_quota_reset=past_date
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        # Calling check_outbound_quota automatically detects past month and resets
        can_send, remaining, reason = mercadopago_service.check_outbound_quota(tenant, db=db)
        assert can_send is True
        assert tenant.messages_sent_this_month == 0
        assert tenant.quota_exhausted_alert_sent is False
        assert remaining == 175  # 150 + 25 rollover
        assert reason == "quota_ok"

        # Now test the CRON endpoint: /api/tenants/cron/run-monthly-quota-reset
        tenant.last_quota_reset = past_date
        tenant.messages_sent_this_month = 100
        db.commit()

        res = client.post("/api/tenants/cron/run-monthly-quota-reset")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["tenants_quota_reset"] >= 1

        db.refresh(tenant)
        assert tenant.messages_sent_this_month == 0

        db.delete(tenant)
        db.commit()
    finally:
        db.close()

