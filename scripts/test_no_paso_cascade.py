#!/usr/bin/env python3
"""
Test script for verifying the 'NO, PASO' flow with 2 live phones:
- Phone 1 (Personal: 5493434536447) -> Candidato #1: Laura Benítez
- Phone 2 (Secundario: 5493435730520) -> Candidato #2: Martín Gómez
"""

import sys
import asyncio
from datetime import datetime, timezone, timedelta

from app.database import SessionLocal
from app.models.tenant import Tenant, Appointment, WaitlistEntry, TenantSession
from app.services.tenant_service import TenantService
from app.services.appointment_service import AppointmentService

async def main():
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.slug == "demo_consultorio").first()
        if not tenant:
            print("❌ No se encontró el tenant 'demo_consultorio'.")
            return

        print(f"🏥 Tenant: {tenant.name} (ID: {tenant.id})")
        
        # Phone numbers
        phone_c1 = "5493434536447"  # Personal (Laura)
        phone_c2 = "5493435730520"  # Secundario (Martín)

        # Ensure active sessions
        TenantService.set_active_session(db, phone_c1, tenant.slug)
        TenantService.set_active_session(db, phone_c2, tenant.slug)

        # Clear old active/notificado waitlist entries for this tenant to ensure clean test
        old_wls = db.query(WaitlistEntry).filter(
            WaitlistEntry.tenant_id == tenant.id,
            WaitlistEntry.status.in_(["activa", "notificado_oferta"])
        ).all()
        for w in old_wls:
            w.status = "cancelada"
        db.commit()

        # Create Candidate 1 (Laura - Personal)
        wl1 = WaitlistEntry(
            tenant_id=tenant.id,
            patient_name="Laura Benítez",
            patient_phone=phone_c1,
            doctor_or_service="Dr. González - Odontología",
            preferred_time_range="Tarde (16 a 19 hs)",
            status="activa"
        )
        db.add(wl1)
        db.commit()
        db.refresh(wl1)

        # Create Candidate 2 (Martín - Secundario)
        wl2 = WaitlistEntry(
            tenant_id=tenant.id,
            patient_name="Martín Gómez",
            patient_phone=phone_c2,
            doctor_or_service="Dr. González - Odontología",
            preferred_time_range="Tarde (16 a 19 hs)",
            status="activa"
        )
        db.add(wl2)
        db.commit()
        db.refresh(wl2)

        print(f"📋 Candidato #1 registrado: {wl1.patient_name} (+{wl1.patient_phone}) [ID: {wl1.id}]")
        print(f"📋 Candidato #2 registrado: {wl2.patient_name} (+{wl2.patient_phone}) [ID: {wl2.id}]")

        # Create a cancelled appointment slot to be offered
        tomorrow_slot = datetime.now(timezone.utc) + timedelta(days=1)
        tomorrow_slot = tomorrow_slot.replace(hour=17, minute=0, second=0, microsecond=0)
        
        apt = Appointment(
            tenant_id=tenant.id,
            patient_name="Esteban Paciente (Canceló)",
            patient_phone="5491145678901",
            doctor_or_service="Dr. González - Odontología",
            appointment_date=tomorrow_slot,
            status="cancelado"
        )
        db.add(apt)
        db.commit()
        db.refresh(apt)

        print(f"🗓️ Turno liberado creado: #{apt.id} para el {apt.appointment_date.strftime('%d/%m a las %H:%M hs')}")
        print("\n🚀 Disparando oferta interactiva al Candidato #1 (Laura / Teléfono Personal)...")

        offered = await AppointmentService.offer_slot_to_next_candidate(db, apt.id)
        if offered:
            print(f"✅ ¡Oferta enviada con éxito a {offered.patient_name} (+{offered.patient_phone})!")
            print("👉 Ahora revisá tu CELULAR PERSONAL (+54 9 343 453-6447) y tocá el botón: [NO, PASO]")
        else:
            print("❌ No se pudo despachar la oferta.")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
