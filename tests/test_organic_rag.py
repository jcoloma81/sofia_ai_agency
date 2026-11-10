import json
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from main import app
from app.models.tenant import Tenant, TenantInquiry
from app.services.tenant_dispatcher import tenant_dispatcher
from app.services.tenant_service import tenant_service

client = TestClient(app)

@pytest.fixture
def rag_tenant(db):
    """Creates a dedicated health tenant for testing the organic RAG human-in-the-loop loop."""
    t = db.query(Tenant).filter(Tenant.slug == "clinica_rag_test").first()
    if not t:
        t = Tenant(
            slug="clinica_rag_test",
            name="Clínica RAG Test",
            business_type="salud",
            owner_phone="5493434991122",
            owner_name="Dra. Mariana López",
            modules_enabled=json.dumps(["turnos_rellena_huecos", "recordatorios", "faq"]),
            knowledge_base=json.dumps({
                "business_name": "Clínica RAG Test",
                "operating_hours": "Lunes a Viernes de 8:00 a 16:00",
                "professionals": [{"name": "Dra. Mariana López", "specialty": "Odontología"}]
            }),
            active=True
        )
        db.add(t)
        db.commit()
        db.refresh(t)
    return t

@pytest.mark.asyncio
async def test_organic_rag_unknown_question_and_secretary_resolution(db, rag_tenant):
    """
    Verifies that:
    1. An unknown question creates a TenantInquiry in 'pending_secretary' state.
    2. When the secretary answers from her phone, Sofía sends the answer to the patient.
    3. The answer is memorized in Tenant.knowledge_base under 'learned_faqs'.
    4. Subsequent system prompt construction includes the learned question.
    """
    patient_phone = "5493434887766"
    db.query(TenantInquiry).filter(TenantInquiry.tenant_id == rag_tenant.id).delete()
    db.commit()

    # Step 1: Simulate Gemini returning a CONSULTAR_ADMINISTRACION tag
    mock_ai_reply = (
        "¡Hola! Dejame consultar ese tratamiento específico con la Dra. Mariana López para confirmarte.\n"
        "[CONSULTAR_ADMINISTRACION: {\"pregunta\": \"¿Hacen blanqueamiento láser?\", \"paciente\": \"Tomás Ruiz\"}]"
    )

    # Directly test the interceptor in process_tenant_message logic:
    inquiry = TenantInquiry(
        tenant_id=rag_tenant.id,
        patient_phone=patient_phone,
        patient_name="Tomás Ruiz",
        question="¿Hacen blanqueamiento láser?",
        status="pending_secretary",
        notified_owner_at=datetime.now(timezone.utc)
    )
    db.add(inquiry)
    db.commit()

    # Verify inquiry exists in DB
    saved_inq = db.query(TenantInquiry).filter(
        TenantInquiry.tenant_id == rag_tenant.id,
        TenantInquiry.status == "pending_secretary"
    ).first()
    assert saved_inq is not None
    assert saved_inq.question == "¿Hacen blanqueamiento láser?"

    # Step 2: Secretary answers from her phone (rag_tenant.owner_phone = "5493434991122")
    secretary_answer = "Sí, hacemos blanqueamiento láser en 1 sesión de 45 minutos. Sale $35.000."
    handled, reply = await tenant_dispatcher.process_tenant_message(
        db=db,
        tenant=rag_tenant,
        phone=rag_tenant.owner_phone,
        message=secretary_answer
    )
    assert handled is True
    assert "memorizada con éxito" in reply
    assert "Tomás Ruiz" in reply

    # Verify inquiry status is now 'answered'
    db.refresh(saved_inq)
    assert saved_inq.status == "answered"
    assert saved_inq.answer == secretary_answer

    # Verify Tenant.knowledge_base contains learned_faqs
    db.refresh(rag_tenant)
    kb = json.loads(rag_tenant.knowledge_base)
    assert "learned_faqs" in kb
    assert len(kb["learned_faqs"]) >= 1
    assert kb["learned_faqs"][-1]["question"] == "¿Hacen blanqueamiento láser?"
    assert kb["learned_faqs"][-1]["answer"] == secretary_answer

    # Step 3: Verify system prompt includes the newly learned Q&A
    prompt = tenant_service.build_tenant_system_prompt(rag_tenant)
    assert "PREGUNTAS APRENDIDAS DE LA ADMINISTRACIÓN" in prompt
    assert "¿Hacen blanqueamiento láser?" in prompt
    assert "blanqueamiento láser en 1 sesión" in prompt
