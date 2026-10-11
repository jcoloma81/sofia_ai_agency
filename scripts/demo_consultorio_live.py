#!/usr/bin/env python3
"""
🏥 SOFÍA AI AGENCY — DEMO INTERACTIVA EN VIVO (CONSULTORIOS & CLÍNICAS)
========================================================================
Herramienta de ventas y simulación en tiempo real para reuniones comerciales
(Google Meet o presenciales) con directores médicos y dueños de consultorios.

Demuestra el flujo completo de:
1. Agenda inicial con un paciente confirmado.
2. Cancelación inesperada del turno.
3. Alerta oficial de Meta en el celular del profesional/dueño.
4. Activación automática 1-a-1 de la Lista de Espera con botones de WhatsApp.
5. Rescate inmediato del hueco y alerta de facturación protegida.
"""

import os
import sys
import asyncio
import argparse
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.tenant import Tenant, Appointment, WaitlistEntry
from app.services.appointment_service import AppointmentService
from app.services.tenant_service import tenant_service
from app.services import whatsapp
from app.config.settings import settings

# ANSI Colors for clean terminal presentation
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
RESET = "\033[0m"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def banner():
    print(f"\n{CYAN}{BOLD}========================================================================{RESET}")
    print(f"{CYAN}{BOLD}   🏥 SOFÍA AI AGENCY — ASISTENTE DE DEMOSTRACIÓN EN VIVO (CONSULTORIOS)  {RESET}")
    print(f"{CYAN}{BOLD}========================================================================{RESET}")
    print(f"{YELLOW}  Muestra en vivo del 'Rellena-Huecos Autónomo' y Alertas Oficiales Meta  {RESET}\n")


def get_or_create_demo_tenant(
    db: Session,
    clinic_name: str = "Consultorios Médicos San Martín (Demo)",
    doctor_name: str = "Dr. Pablo Rossi",
    doctor_phone: str = "5493434536447",
    doctor_email: Optional[str] = "dr.rossi@consultoriosdemo.com",
    slug: str = "demo_consultorio",
    deep_link_keyword: Optional[str] = None
) -> Tenant:
    """
    Creates or updates the dedicated demo tenant in the database.
    Ensures correct modules and clean state.
    """
    if not deep_link_keyword:
        deep_link_keyword = f"Demo_{slug.capitalize()}"

    clean_phone = "".join(filter(str.isdigit, doctor_phone))
    tenant = db.query(Tenant).filter(Tenant.slug == slug).first()

    if not tenant:
        tenant = Tenant(
            slug=slug,
            name=clinic_name,
            business_type="salud",
            owner_name=doctor_name,
            owner_phone=clean_phone,
            owner_email=doctor_email,
            deep_link_keyword=deep_link_keyword,
            branding_header=f"🏥 *{clinic_name}*",
            modules_enabled='["turnos_rellena_huecos", "recordatorios", "faq"]',
            knowledge_base='{"especialidad": "Medicina General y Odontología", "horarios": "Lunes a Viernes 08:00 a 20:00 hs"}',
            active=True
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
    else:
        tenant.name = clinic_name
        tenant.owner_name = doctor_name
        tenant.owner_phone = clean_phone
        tenant.owner_email = doctor_email
        tenant.deep_link_keyword = deep_link_keyword
        tenant.branding_header = f"🏥 *{clinic_name}*"
        tenant.active = True
        db.commit()
        db.refresh(tenant)

    return tenant


def clean_demo_scenario(db: Session, tenant_id: int):
    """
    Deletes prior demo appointments and waitlist entries for a 100% clean slate.
    """
    db.query(Appointment).filter(Appointment.tenant_id == tenant_id).delete()
    db.query(WaitlistEntry).filter(WaitlistEntry.tenant_id == tenant_id).delete()
    db.commit()


def setup_demo_scenario(
    db: Session,
    tenant_id: int,
    doctor_name: str = "Dr. Pablo Rossi - Odontología",
    patient_name: str = "Martín Gómez",
    patient_phone: str = "5493434536447",
    waitlist_patient_name: str = "Laura Benítez",
    waitlist_patient_phone: str = "5493434536447",
    appointment_time: Optional[datetime] = None
) -> Tuple[Appointment, WaitlistEntry]:
    """
    Sets up the clean demo scene:
    - 1 Active appointment for today at 17:00 hs.
    - 1 Active waitlist candidate waiting for an opening.
    """
    clean_demo_scenario(db, tenant_id)

    if not appointment_time:
        today = utc_now().date()
        appointment_time = datetime(today.year, today.month, today.day, 17, 0, tzinfo=timezone.utc)

    # 1. Create Appointment
    apt = Appointment(
        tenant_id=tenant_id,
        patient_name=patient_name,
        patient_phone="".join(filter(str.isdigit, patient_phone)),
        doctor_or_service=doctor_name,
        appointment_date=appointment_time,
        status="agendado",
        notes="Turno particular agendado para control"
    )
    db.add(apt)
    db.commit()
    db.refresh(apt)

    # 2. Create Waitlist Entry
    wl = WaitlistEntry(
        tenant_id=tenant_id,
        patient_name=waitlist_patient_name,
        patient_phone="".join(filter(str.isdigit, waitlist_patient_phone)),
        doctor_or_service=doctor_name,
        preferred_time_range="Por la tarde",
        status="activa"
    )
    db.add(wl)
    db.commit()
    db.refresh(wl)

    return apt, wl


async def execute_cancellation_step(
    db: Session,
    appointment_id: int,
    reason: str = "Imprevisto laboral urgente"
) -> Dict[str, Any]:
    """
    Executes the patient cancellation and triggers the cascade:
    - Cancels appointment
    - Sends WhatsApp/email alert to doctor
    - Offers liberated slot to waitlist candidate #1
    """
    return await AppointmentService.cancel_and_fill_gap(db, appointment_id, reason=reason)


async def execute_claim_step(
    db: Session,
    appointment_id: int,
    waitlist_id: int
) -> bool:
    """
    Simulates the waitlist candidate tapping 'TOMAR TURNO':
    - Assigns slot to waitlist candidate
    - Sends confirmation to patient
    - Sends victory alert to doctor ('Turno rescatado con éxito')
    """
    return await AppointmentService.claim_waitlist_slot(db, appointment_id, waitlist_id)


def print_status_box(title: str, lines: list, color: str = GREEN):
    print(f"\n{color}{BOLD}┌────────────────────────────────────────────────────────────────────────┐{RESET}")
    print(f"{color}{BOLD}│ {title.ljust(70)} │{RESET}")
    print(f"{color}{BOLD}├────────────────────────────────────────────────────────────────────────┤{RESET}")
    for line in lines:
        print(f"{color}│ {line.ljust(70)} │{RESET}")
    print(f"{color}{BOLD}└────────────────────────────────────────────────────────────────────────┘{RESET}\n")


async def run_interactive_wizard():
    banner()
    db = SessionLocal()

    # Default configuration
    clinic_name = "Consultorios Médicos San Martín (Demo)"
    doctor_name = "Dr. Pablo Rossi"
    doctor_phone = "5493434536447"
    doctor_email = "dr.rossi@consultoriosdemo.com"
    patient_name = "Martín Gómez"
    patient_phone = "5493434536447"
    waitlist_name = "Laura Benítez"
    waitlist_phone = "5493434536447"

    tenant = get_or_create_demo_tenant(
        db=db,
        clinic_name=clinic_name,
        doctor_name=doctor_name,
        doctor_phone=doctor_phone,
        doctor_email=doctor_email
    )

    current_apt: Optional[Appointment] = None
    current_wl: Optional[WaitlistEntry] = None

    while True:
        print(f"{BOLD}Configuración Actual:{RESET}")
        print(f"  • {BOLD}Clínica:{RESET} {CYAN}{clinic_name}{RESET} ({doctor_name})")
        print(f"  • {BOLD}WhatsApp del Profesional:{RESET} {CYAN}+{doctor_phone}{RESET} | Email: {CYAN}{doctor_email}{RESET}")
        print(f"  • {BOLD}Paciente Activo:{RESET} {patient_name} (+{patient_phone})")
        print(f"  • {BOLD}Paciente Lista Espera:{RESET} {waitlist_name} (+{waitlist_phone})\n")

        print(f"{BOLD}Menú de Opciones:{RESET}")
        print(f"  {GREEN}[1]{RESET} 📋 Preparar y Resetear Escenario Demo (Crear Turno 17:00 hs + Lista Espera)")
        print(f"  {YELLOW}[2]{RESET} ⚠️ Simular Cancelación de Turno (Martín cancela -> Alerta Dr + Oferta a Laura)")
        print(f"  {MAGENTA}[3]{RESET} 🎯 Simular Rescate de Turno (Laura acepta -> Hueco cubierto + Alerta Triunfal)")
        print(f"  {CYAN}[4]{RESET} 🚀 MODO SHOW EN VIVO COMPLETO (Paso a paso guiado con [ENTER])")
        print(f"  {BOLD}[5]{RESET} ⚙️ Personalizar Datos (Nombre del Doctor / Teléfonos para la reunión)")
        print(f"  {BOLD}[6]{RESET} 🧹 Limpiar Escenario (Borrar turnos de demo)")
        print(f"  {RED}[0]{RESET} ❌ Salir")

        try:
            choice = input(f"\n{BOLD}Seleccioná una opción [0-6]: {RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n👋 Saliendo de la demo.")
            break

        if choice == "0":
            print("\n👋 ¡Éxitos en la reunión comercial!\n")
            break

        elif choice == "1":
            print(f"\n⏳ {CYAN}Inicializando escenario en la base de datos...{RESET}")
            current_apt, current_wl = setup_demo_scenario(
                db=db,
                tenant_id=tenant.id,
                doctor_name=f"{doctor_name} - Odontología",
                patient_name=patient_name,
                patient_phone=patient_phone,
                waitlist_patient_name=waitlist_name,
                waitlist_patient_phone=waitlist_phone
            )
            date_str = current_apt.appointment_date.strftime("%d/%m a las %H:%M hs")
            print_status_box(
                "✅ ESCENARIO DEMO PREPARADO CON ÉXITO",
                [
                    f"1. Turno #{current_apt.id} agendado para '{patient_name}' a las {date_str}.",
                    f"2. Paciente #{current_wl.id} '{waitlist_name}' registrada en Lista de Espera.",
                    f"3. Consultorio '{tenant.name}' listo para la llamada."
                ],
                GREEN
            )

        elif choice == "2":
            if not current_apt:
                # Find most recent
                current_apt = db.query(Appointment).filter(
                    Appointment.tenant_id == tenant.id,
                    Appointment.status == "agendado"
                ).order_by(Appointment.id.desc()).first()

            if not current_apt:
                print(f"{RED}❌ No hay turnos agendados en el escenario. Ejecutá la opción [1] primero.{RESET}")
                continue

            print(f"\n⏳ {YELLOW}Ejecutando cancelación y activando Lista de Espera autónoma...{RESET}")
            res = await execute_cancellation_step(db, current_apt.id, reason="Imprevisto laboral de último momento")
            
            # Refresh entries
            db.refresh(current_apt)
            current_wl = db.query(WaitlistEntry).filter(
                WaitlistEntry.tenant_id == tenant.id,
                WaitlistEntry.offered_appointment_id == current_apt.id
            ).first()

            print_status_box(
                "⚠️ CANCELACIÓN PROCESADA & RESCATE ACTIVADO",
                [
                    f"• Turno #{current_apt.id} marcado como 'cancelado'.",
                    f"• Alerta de Cancelación despachada a +{doctor_phone} ({doctor_email}).",
                    f"• Paciente ofrecido: '{res.get('candidate_offered')}' (+{waitlist_phone}).",
                    f"• Mensaje interactivo de WhatsApp enviado con botones de confirmación."
                ],
                YELLOW
            )

        elif choice == "3":
            if not current_apt or not current_wl:
                # Find offered waitlist entry
                current_wl = db.query(WaitlistEntry).filter(
                    WaitlistEntry.tenant_id == tenant.id,
                    WaitlistEntry.status == "notificado_oferta"
                ).order_by(WaitlistEntry.id.desc()).first()

                if current_wl:
                    current_apt = db.query(Appointment).filter(Appointment.id == current_wl.offered_appointment_id).first()

            if not current_apt or not current_wl:
                print(f"{RED}❌ No hay ninguna oferta de turno pendiente para tomar. Ejecutá [1] y [2] primero.{RESET}")
                continue

            print(f"\n⏳ {MAGENTA}Simulando aceptación del paciente en lista de espera...{RESET}")
            success = await execute_claim_step(db, current_apt.id, current_wl.id)

            if success:
                db.refresh(current_apt)
                date_str = current_apt.appointment_date.strftime("%d/%m a las %H:%M hs")
                print_status_box(
                    "🎉 ¡TURNO RESCATADO CON ÉXITO!",
                    [
                        f"• Turno de las {date_str} reasignado a '{current_wl.patient_name}'.",
                        f"• Estado del turno: 'rellenado_con_exito'.",
                        f"• Confirmación enviada al paciente por WhatsApp.",
                        f"• ALERTA TRIUNFAL enviada al Doctor: 'Cero pérdida de facturación'."
                    ],
                    MAGENTA
                )
            else:
                print(f"{RED}❌ No se pudo completar la asignación del turno.{RESET}")

        elif choice == "4":
            # Guided show mode
            print(f"\n{CYAN}{BOLD}🎬 INICIANDO MODO SHOW EN VIVO...{RESET}")
            print(f"Podés hablar en el Meet y presionar [ENTER] en cada punto para que los mensajes caigan en vivo.\n")

            # Paso 1: Setup
            current_apt, current_wl = setup_demo_scenario(
                db=db,
                tenant_id=tenant.id,
                doctor_name=f"{doctor_name} - Odontología",
                patient_name=patient_name,
                patient_phone=patient_phone,
                waitlist_patient_name=waitlist_name,
                waitlist_patient_phone=waitlist_phone
            )
            date_str = current_apt.appointment_date.strftime("%d/%m a las %H:%M hs")
            print(f"{GREEN}▶ PASO 1 (Escenario Inicial):{RESET}")
            print(f"  El paciente {patient_name} tiene turno confirmado hoy a las {date_str}.")
            print(f"  La paciente {waitlist_name} está registrada en lista de espera.")
            input(f"\n{BOLD}👉 Explicá la agenda inicial al cliente y presioná [ENTER] para simular la cancelación...{RESET}")

            # Paso 2: Cancelación
            print(f"\n{YELLOW}▶ PASO 2 (El Problema - Turno Cancelado):{RESET}")
            res = await execute_cancellation_step(db, current_apt.id, reason="Imprevisto personal de último momento")
            print(f"  🚨 {patient_name} acaba de cancelar su turno de las {date_str}.")
            print(f"  📲 Alerta de cancelación enviada al Doctor (+{doctor_phone}).")
            print(f"  🚀 Sofía le acaba de enviar la oferta de WhatsApp a {waitlist_name}.")
            input(f"\n{BOLD}👉 Mostrá la pantalla/alerta recibida y presioná [ENTER] para que Laura acepte el turno...{RESET}")

            # Paso 3: Aceptación
            print(f"\n{MAGENTA}▶ PASO 3 (La Solución - Rescate Autónomo):{RESET}")
            await execute_claim_step(db, current_apt.id, current_wl.id)
            print(f"  🎉 {waitlist_name} aceptó el turno.")
            print(f"  ✅ Turno confirmado y reasignado en la agenda.")
            print(f"  💰 Alerta de Facturación Protegida enviada al Doctor.")
            print(f"\n{GREEN}{BOLD}✨ Fin del Show: El cliente vio el turno recuperarse en tiempo real.{RESET}\n")

        elif choice == "5":
            print(f"\n{BOLD}⚙️ Personalización de Datos para la Demostración:{RESET}")
            new_clinic = input(f"Nombre de la Clínica [{clinic_name}]: ").strip()
            if new_clinic:
                clinic_name = new_clinic
            new_doc = input(f"Nombre del Doctor [{doctor_name}]: ").strip()
            if new_doc:
                doctor_name = new_doc
            new_phone = input(f"WhatsApp del Doctor (+549...) [{doctor_phone}]: ").strip()
            if new_phone:
                doctor_phone = "".join(filter(str.isdigit, new_phone))
            new_email = input(f"Email del Doctor [{doctor_email}]: ").strip()
            if new_email:
                doctor_email = new_email
            new_wl_phone = input(f"WhatsApp de la Paciente en Lista de Espera [{waitlist_phone}]: ").strip()
            if new_wl_phone:
                waitlist_phone = "".join(filter(str.isdigit, new_wl_phone))

            tenant = get_or_create_demo_tenant(
                db=db,
                clinic_name=clinic_name,
                doctor_name=doctor_name,
                doctor_phone=doctor_phone,
                doctor_email=doctor_email
            )
            print(f"\n{GREEN}✅ Datos actualizados correctamente.{RESET}\n")

        elif choice == "6":
            clean_demo_scenario(db, tenant.id)
            current_apt = None
            current_wl = None
            print(f"\n{GREEN}🧹 Escenario limpiado. Base de datos sin turnos de demo.{RESET}\n")

    db.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Sofía AI Agency — Live Healthcare Demo Runner")
    parser.add_argument("--setup", action="store_true", help="Only setup the demo scene and exit")
    parser.add_argument("--cancel", action="store_true", help="Simulate cancellation for active demo appointment")
    parser.add_argument("--claim", action="store_true", help="Simulate claim for offered waitlist entry")
    parser.add_argument("--clean", action="store_true", help="Clean up demo scenario and exit")
    parser.add_argument("--doctor-phone", type=str, default="5493434536447", help="Doctor notification phone")
    parser.add_argument("--doctor-name", type=str, default="Dr. Pablo Rossi", help="Doctor name")
    parser.add_argument("--clinic-name", type=str, default="Consultorios Médicos San Martín (Demo)", help="Clinic name")
    parser.add_argument("--patient-phone", type=str, default="5493434536447", help="Patient phone")
    parser.add_argument("--waitlist-phone", type=str, default="5493434536447", help="Waitlist candidate phone")
    parser.add_argument("--non-interactive", action="store_true", help="Run without user prompts (for tests/automation)")
    return parser.parse_args()


async def main():
    args = parse_args()

    if args.non_interactive or args.setup or args.cancel or args.claim or args.clean:
        db = SessionLocal()
        tenant = get_or_create_demo_tenant(
            db=db,
            clinic_name=args.clinic_name,
            doctor_name=args.doctor_name,
            doctor_phone=args.doctor_phone
        )

        if args.clean:
            clean_demo_scenario(db, tenant.id)
            print("✅ Demo scenario cleaned.")
            db.close()
            return

        if args.setup:
            apt, wl = setup_demo_scenario(
                db=db,
                tenant_id=tenant.id,
                doctor_name=f"{args.doctor_name} - Odontología",
                patient_phone=args.patient_phone,
                waitlist_patient_phone=args.waitlist_phone
            )
            print(f"✅ Setup complete: Apt #{apt.id}, Waitlist #{wl.id}")

        if args.cancel:
            apt = db.query(Appointment).filter(
                Appointment.tenant_id == tenant.id,
                Appointment.status == "agendado"
            ).order_by(Appointment.id.desc()).first()
            if apt:
                res = await execute_cancellation_step(db, apt.id)
                print(f"✅ Cancellation executed: {res}")
            else:
                print("❌ No active appointment to cancel.")

        if args.claim:
            wl = db.query(WaitlistEntry).filter(
                WaitlistEntry.tenant_id == tenant.id,
                WaitlistEntry.status == "notificado_oferta"
            ).order_by(WaitlistEntry.id.desc()).first()
            if wl and wl.offered_appointment_id:
                success = await execute_claim_step(db, wl.offered_appointment_id, wl.id)
                print(f"✅ Claim executed: {success}")
            else:
                print("❌ No pending offer to claim.")

        db.close()
        return

    # Interactive Wizard Mode
    await run_interactive_wizard()


if __name__ == "__main__":
    asyncio.run(main())
