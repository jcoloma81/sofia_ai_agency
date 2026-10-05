import asyncio
import logging
from datetime import datetime, timezone, timedelta
from app.database import SessionLocal
from app.models.tenant import Tenant, Appointment, WaitlistEntry, MembershipPayment, InactiveCustomer
from app.services.tenant_service import tenant_service
from app.services.tenant_dispatcher import tenant_dispatcher
from app.services.appointment_service import appointment_service
from app.services.billing_service import billing_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_suite")

async def run_enterprise_tests():
    db = SessionLocal()
    print("=" * 70)
    print("🧪 INICIANDO TEST SUITE ENTERPRISE MULTI-TENANT DE SOFÍA")
    print("=" * 70)

    # -------------------------------------------------------------
    # TEST 1: Tenant Resolution & Deep Linking
    # -------------------------------------------------------------
    print("\n🔹 TEST 1: Resolución de Inquilino (Tenant) por Deep Link")
    phone_marina = "5493434778899"
    msg_deep = "Hola quiero consultar por un turno #clinica_alvear"
    tenant, cleaned = tenant_service.resolve_incoming_tenant(db, phone_marina, msg_deep)
    assert tenant is not None, "Error: Tenant no resuelto por hashtag"
    assert tenant.slug == "clinica_alvear", f"Error: Slug incorrecto {tenant.slug}"
    print(f"✅ Tenant resuelto con éxito: '{tenant.name}' ({tenant.business_type})")

    # -------------------------------------------------------------
    # TEST 2: Cancelación de Turno y 'Rellena-Huecos' en Tiempo Real
    # -------------------------------------------------------------
    print("\n🔹 TEST 2: Cancelación de Turno y Disparo de 'Rellena-Huecos'")
    # Reset/ensure María Gómez appointment is in 'agendado' state for idempotent test runs
    apt = db.query(Appointment).filter(Appointment.patient_name.in_(["María Gómez", "Laura Santillán"])).first()
    if apt:
        apt.patient_name = "María Gómez"
        apt.patient_phone = "5493434556677"
        apt.status = "agendado"
        db.commit()
        db.refresh(apt)
    
    cand = db.query(WaitlistEntry).filter(WaitlistEntry.patient_name == "Laura Santillán").first()
    if not cand:
        cand = WaitlistEntry(
            tenant_id=apt.tenant_id,
            patient_name="Laura Santillán",
            patient_phone="5493434123456",
            doctor_or_service="Dra. Silvina Gómez - Odontología General",
            status="activa"
        )
        db.add(cand)
        db.commit()
    else:
        cand.status = "activa"
        cand.offered_at = None
        db.commit()

    assert apt is not None, "Error: Turno de María Gómez no encontrado"

    # María cancels her appointment
    res_cancel = await appointment_service.cancel_and_fill_gap(db, apt.id, reason="Estoy con fiebre")
    assert res_cancel["status"] == "success"
    assert res_cancel["waitlist_pings_sent"] > 0
    print(f"✅ Turno #{apt.id} cancelado correctamente.")
    print(f"⚡ Rellena-Huecos activado: {res_cancel['waitlist_pings_sent']} pacientes en lista de espera notificados!")

    # Verify waitlist candidate status
    cand = db.query(WaitlistEntry).filter(WaitlistEntry.patient_name == "Laura Santillán").first()
    assert cand.status == "notificado_oferta"
    print(f"✅ Paciente '{cand.patient_name}' recibió oferta de turno liberado.")

    # -------------------------------------------------------------
    # TEST 3: Candidato de Lista de Espera toma el turno (TOMAR TURNO)
    # -------------------------------------------------------------
    print("\n🔹 TEST 3: Asignación Inmediata de Turno Liberado a Lista de Espera")
    claimed = await appointment_service.claim_waitlist_slot(db, apt.id, cand.id)
    assert claimed is True

    # Re-fetch appointment
    db.refresh(apt)
    assert apt.status == "rellenado_con_exito"
    assert apt.patient_name == "Laura Santillán"
    print(f"🎉 Turno #{apt.id} cubierto exitosamente por {apt.patient_name}! (Status: {apt.status})")

    # -------------------------------------------------------------
    # TEST 4: Cobranzas y Cuotas de Gimnasio (Iron Gym)
    # -------------------------------------------------------------
    print("\n🔹 TEST 4: Cobranzas de Cuotas con Mercado Pago (Iron Gym)")
    gym_tenant = tenant_service.get_tenant_by_slug(db, "iron_gym")
    assert gym_tenant is not None

    mem = db.query(MembershipPayment).filter(
        MembershipPayment.member_name == "Lucas Martínez"
    ).first()
    assert mem is not None
    print(f"✅ Socio: {mem.member_name} | Plan: {mem.plan_name} | Monto: ${mem.amount} ARS")
    print(f"💳 Link de pago generado: {mem.mp_payment_link}")

    # Simulate CRON scan for due reminders
    reminders = await billing_service.scan_and_send_due_reminders(db)
    print(f"✅ Recordatorios de cobro procesados por CRON: {reminders}")

    # -------------------------------------------------------------
    # TEST 5: Reactivador de Clientes / Socios Dormidos
    # -------------------------------------------------------------
    print("\n🔹 TEST 5: Campaña Reactivadora de Socios Dormidos (Promo Verano)")
    # Reset dormant customer status for idempotent test runs
    dormant_lead = db.query(InactiveCustomer).filter(
        InactiveCustomer.customer_name == "Agustín Morales"
    ).first()
    if dormant_lead:
        dormant_lead.status = "dormido"
        dormant_lead.contacted_at = None
        db.commit()

    reactivator_res = await billing_service.run_dormant_reactivator_campaign(db, "iron_gym")
    assert reactivator_res["status"] == "success"
    print(f"🚀 Campaña completada: {reactivator_res['messages_dispatched']} ex-socios contactados con la promo.")

    # Verify dormant status changed to 'contactado'
    dormant_lead = db.query(InactiveCustomer).filter(
        InactiveCustomer.customer_name == "Agustín Morales"
    ).first()
    assert dormant_lead.status == "contactado"
    print(f"✅ Lead dormido '{dormant_lead.customer_name}' ahora está en estado: {dormant_lead.status}")

    # -------------------------------------------------------------
    # TEST 6: Lead responde 'QUIERO LA PROMO'
    # -------------------------------------------------------------
    print("\n🔹 TEST 6: Socio responde 'QUIERO LA PROMO'")
    handled, reply = await tenant_dispatcher.process_tenant_message(
        db=db,
        tenant=gym_tenant,
        phone=dormant_lead.customer_phone,
        message="Quiero la promo de verano!"
    )
    assert handled is True
    db.refresh(dormant_lead)
    assert dormant_lead.status == "interesado"
    print(f"🔥 Lead calificado y alertado al dueño! Status: {dormant_lead.status}")

    # -------------------------------------------------------------
    # TEST 7: Adelanta-Turnos (Fast-Track) cuando la Lista de Espera está Vacía
    # -------------------------------------------------------------
    print("\n🔹 TEST 7: 'Adelanta-Turnos' Fast-Track (Vacante sin Lista de Espera)")
    clinic_tenant = tenant_service.get_tenant_by_slug(db, "clinica_alvear")
    now_utc = datetime.now(timezone.utc)
    
    # Create an empty slot for tomorrow
    vacant_slot = Appointment(
        tenant_id=clinic_tenant.id,
        patient_name="Paciente Que Cancelo",
        patient_phone="5493434000000",
        doctor_or_service="Dra. Silvina Gómez - Odontología General",
        appointment_date=now_utc + timedelta(days=1),
        status="cancelado"
    )
    # Create a future appointment for next week
    future_patient = Appointment(
        tenant_id=clinic_tenant.id,
        patient_name="Carlos Ruiz",
        patient_phone="5493434888999",
        doctor_or_service="Dra. Silvina Gómez - Odontología General",
        appointment_date=now_utc + timedelta(days=6),
        status="confirmado"
    )
    db.add(vacant_slot)
    db.add(future_patient)
    db.commit()
    db.refresh(vacant_slot)
    db.refresh(future_patient)

    # Trigger offer_slot_to_next_candidate: waitlist is empty, so it falls back to Fast-Track!
    fast_cand = await appointment_service.offer_slot_to_next_candidate(db, vacant_slot.id)
    assert fast_cand is not None
    assert fast_cand.patient_name == "Carlos Ruiz"
    print(f"🚀 'Adelanta-Turnos' activado con éxito: Vacante de mañana ofrecida a '{fast_cand.patient_name}' (Turno original: +6 días)")

    # Simulate Carlos clicking [SÍ, ADELANTAR]
    btn_id = f"fast_track_accept_{vacant_slot.id}_{future_patient.id}"
    handled_btn, reply_btn = await tenant_dispatcher.process_tenant_message(
        db=db,
        tenant=clinic_tenant,
        phone=future_patient.patient_phone,
        message="",
        interactive_button_id=btn_id
    )
    assert handled_btn is True
    db.refresh(vacant_slot)
    db.refresh(future_patient)
    assert vacant_slot.status == "rellenado_con_exito"
    assert vacant_slot.patient_name == "Carlos Ruiz"
    assert future_patient.status == "liberado_por_adelanto"
    print(f"🎉 Carlos Ruiz adelantó su turno para mañana! Slot #{vacant_slot.id} rellenado con éxito.")
    print(f"📅 El turno original #{future_patient.id} quedó: '{future_patient.status}' para nuevos pacientes.")

    # -------------------------------------------------------------
    # TEST 8: Secretaria consulta a Sofía por WhatsApp sobre los Huecos
    # -------------------------------------------------------------
    print("\n🔹 TEST 8: Secretaría consulta a Sofía por WhatsApp: '¿Quedó algún hueco para mañana?'")
    sec_reply = await tenant_dispatcher.process_owner_instruction(
        db=db,
        tenant=clinic_tenant,
        message="Sofi, ¿quedó algún hueco para mañana?"
    )
    assert sec_reply is not None
    assert "ESTADO DE AGENDA PARA MAÑANA" in sec_reply
    print("✅ Sofía respondió con el reporte en tiempo real:")
    print("-" * 50)
    print(sec_reply)
    print("-" * 50)

    print("\n" + "=" * 70)
    print("🏆 ¡TODOS LOS 8 TESTS ENTERPRISE PASARON AL 100%! SISTEMA LISTO PARA SALIR A LA CALLE")
    print("=" * 70)
    db.close()

if __name__ == "__main__":
    asyncio.run(run_enterprise_tests())
