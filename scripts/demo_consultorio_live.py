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
    patient_phone: str = "5491145678901",
    waitlist_patient_name: str = "Laura Benítez",
    waitlist_patient_phone: str = "5493435730520",
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

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant:
        TenantService.set_active_session(db, patient_phone, tenant.slug)
        TenantService.set_active_session(db, waitlist_patient_phone, tenant.slug)

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


async def execute_reject_step(
    db: Session,
    appointment_id: int,
    waitlist_id: int
) -> bool:
    """
    Simulates the waitlist candidate tapping 'NO, PASO':
    - Keeps their priority in waitlist
    - Sends warm rioplatense response to candidate
    - Passes the slot to next candidate / fast-track
    """
    return await AppointmentService.reject_waitlist_slot(db, appointment_id, waitlist_id)


async def simulate_autonomous_booking_step(
    db: Session,
    tenant_id: int,
    patient_name: str = "Martín Gómez",
    patient_phone: str = "5491145678901",
    doctor_name: str = "Dr. Pablo Rossi - Odontología",
    appointment_time: Optional[datetime] = None
) -> Appointment:
    """
    Simulates the patient requesting an appointment via WhatsApp autonomously:
    - Creates Appointment record in DB
    - Sends WhatsApp confirmation to patient
    - Sends Executive Alert to Doctor / Owner
    """
    if not appointment_time:
        today = utc_now().date()
        appointment_time = datetime(today.year, today.month, today.day, 17, 0, tzinfo=timezone.utc)

    apt = AppointmentService.create_appointment(
        db=db,
        tenant_id=tenant_id,
        patient_name=patient_name,
        patient_phone=patient_phone,
        doctor_or_service=doctor_name,
        appointment_date=appointment_time,
        notes="Turno agendado de forma 100% autónoma por WhatsApp"
    )

    tenant = apt.tenant
    if tenant:
        TenantService.set_active_session(db, patient_phone, tenant.slug)
    date_str = apt.appointment_date.strftime("%d/%m a las %H:%M hs")

    # Send confirmation to patient
    confirm_msg = (
        f"¡Hola *{patient_name}*! Tu turno con *{doctor_name}* quedó agendado con éxito para el día *{date_str}*.\n\n"
        f"📍 Te esperamos en el consultorio. Si tenés alguna duda previa o imprevisto, avisanos por este mismo medio."
    )
    await tenant_service.send_branded_notification(tenant, patient_phone, confirm_msg)

    # Send executive alert to Doctor
    if tenant and tenant.owner_phone:
        owner_alert = (
            f"📅 *NUEVO TURNO AGENDADO (Autónomo)*\n\n"
            f"👤 Paciente: *{patient_name}*\n"
            f"📱 Celular: +{patient_phone}\n"
            f"👨‍⚕️ Profesional: *{doctor_name}*\n"
            f"📅 Fecha: *{date_str}*\n\n"
            f"✨ Agendado 100% de forma autónoma por WhatsApp sin intervención de la secretaria."
        )
        await whatsapp.send_owner_or_admin_alert(
            to_phone=tenant.owner_phone,
            fallback_text=owner_alert,
            business_name=tenant.name,
            event_type="Nuevo Turno Agendado (Autónomo)",
            client_title=f"{patient_name} (+{patient_phone})",
            details_summary=f"Turno: {date_str} ({doctor_name})"
        )

    return apt


def display_live_database(db: Session, tenant_id: int):
    """
    Displays the current database state in a clean, high-contrast terminal table
    so the doctor/client can see real-time updates in Google Meet or in person.
    """
    apts = db.query(Appointment).filter(Appointment.tenant_id == tenant_id).order_by(Appointment.id.asc()).all()
    wls = db.query(WaitlistEntry).filter(WaitlistEntry.tenant_id == tenant_id).order_by(WaitlistEntry.id.asc()).all()

    print(f"\n{CYAN}{BOLD}========================================================================{RESET}")
    print(f"{CYAN}{BOLD}   📊 BASE DE DATOS EN VIVO — AGENDA & LISTA DE ESPERA (SQLITE / POSTGRES) {RESET}")
    print(f"{CYAN}{BOLD}========================================================================{RESET}")

    print(f"\n{BOLD}1. TABLA: APPOINTMENTS (Turnos Registrados):{RESET}")
    if not apts:
        print(f"   {YELLOW}(No hay turnos registrados en este momento){RESET}")
    else:
        print(f"   {'ID':<5} | {'PACIENTE':<18} | {'TELÉFONO':<15} | {'FECHA / HORA':<18} | {'ESTADO':<22}")
        print(f"   {'-'*5}-+-{'-'*18}-+-{'-'*15}-+-{'-'*18}-+-{'-'*22}")
        for a in apts:
            d_str = a.appointment_date.strftime("%d/%m %H:%M hs")
            st_color = GREEN if a.status in ["agendado", "confirmado", "rellenado_con_exito"] else (RED if a.status == "cancelado" else YELLOW)
            print(f"   #{a.id:<4} | {a.patient_name:<18} | +{a.patient_phone:<14} | {d_str:<18} | {st_color}{a.status:<22}{RESET}")

    print(f"\n{BOLD}2. TABLA: WAITLIST_ENTRIES (Lista de Espera Activa):{RESET}")
    if not wls:
        print(f"   {YELLOW}(No hay pacientes en lista de espera en este momento){RESET}")
    else:
        print(f"   {'ID':<5} | {'PACIENTE':<18} | {'TELÉFONO':<15} | {'PREFERENCIA':<18} | {'ESTADO':<22}")
        print(f"   {'-'*5}-+-{'-'*18}-+-{'-'*15}-+-{'-'*18}-+-{'-'*22}")
        for w in wls:
            st_color = GREEN if w.status == "turno_tomado" else (YELLOW if w.status == "notificado_oferta" else (RED if w.status == "rechazado" else CYAN))
            print(f"   #{w.id:<4} | {w.patient_name:<18} | +{w.patient_phone:<14} | {w.preferred_time_range[:18]:<18} | {st_color}{w.status:<22}{RESET}")
    print(f"{CYAN}========================================================================{RESET}\n")


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
    patient_phone = "5491145678901"
    waitlist_name = "Laura Benítez"
    waitlist_phone = "5493435730520"

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

        print(f"{BOLD}Menú de Opciones para la Demostración:{RESET}")
        print(f"  {CYAN}[1]{RESET} 📊 Ver Base de Datos en Pantalla en Vivo (Agenda & Lista de Espera)")
        print(f"  {GREEN}[2]{RESET} 💬 Simular Paciente Agendando de Forma Autónoma (Paso 1 -> Crea Turno en DB + Alerta Dr)")
        print(f"  {YELLOW}[3]{RESET} ⚠️ Simular Cancelación de Turno (Paso 2 -> Turno Cancelado + Alerta Dr + Oferta a Laura)")
        print(f"  {MAGENTA}[4]{RESET} 🙅 Simular Rechazo de Adelantamiento ('NO, PASO' con respuesta cálida rioplatense)")
        print(f"  {GREEN}[5]{RESET} 🎯 Simular Aceptación de Adelantamiento ('TOMAR TURNO' -> Turno Rescatado + Alerta Triunfal)")
        print(f"  {CYAN}[6]{RESET} 🚀 MODO SHOW COMPLETO PASO A PASO (Guiado con [ENTER] para reunión)")
        print(f"  {BOLD}[7]{RESET} ⚙️ Personalizar Datos (Nombre del Doctor / Teléfonos para la reunión)")
        print(f"  {BOLD}[8]{RESET} 🧹 Limpiar Escenario (Borrar turnos de demo)")
        print(f"  {RED}[0]{RESET} ❌ Salir")

        try:
            choice = input(f"\n{BOLD}Seleccioná una opción [0-8]: {RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n👋 Saliendo de la demo.")
            break

        if choice == "0":
            print("\n👋 ¡Éxitos en la reunión comercial!\n")
            break

        elif choice == "1":
            display_live_database(db, tenant.id)

        elif choice == "2":
            print(f"\n⏳ {CYAN}Simulando paciente solicitando turno por WhatsApp...{RESET}")
            current_apt = await simulate_autonomous_booking_step(
                db=db,
                tenant_id=tenant.id,
                patient_name=patient_name,
                patient_phone=patient_phone,
                doctor_name=f"{doctor_name} - Odontología"
            )
            # Ensure waitlist candidate exists too
            current_wl = db.query(WaitlistEntry).filter(
                WaitlistEntry.tenant_id == tenant.id,
                WaitlistEntry.patient_phone == "".join(filter(str.isdigit, waitlist_phone))
            ).first()
            if not current_wl:
                current_wl = WaitlistEntry(
                    tenant_id=tenant.id,
                    patient_name=waitlist_name,
                    patient_phone="".join(filter(str.isdigit, waitlist_phone)),
                    doctor_or_service=f"{doctor_name} - Odontología",
                    preferred_time_range="Por la tarde",
                    status="activa"
                )
                db.add(current_wl)
                db.commit()
                db.refresh(current_wl)

            date_str = current_apt.appointment_date.strftime("%d/%m a las %H:%M hs")
            print_status_box(
                "📅 TURNO AGENDADO DE FORMA 100% AUTÓNOMA",
                [
                    f"1. Paciente '{patient_name}' agendó para {date_str}.",
                    f"2. Estado en BD: 'agendado'. Creado en la tabla Appointments.",
                    f"3. Confirmación con pautas enviada al WhatsApp del paciente.",
                    f"4. ALERTA EJECUTIVA despachada al celular del Doctor (+{doctor_phone})."
                ],
                GREEN
            )
            display_live_database(db, tenant.id)

        elif choice == "3":
            if not current_apt:
                current_apt = db.query(Appointment).filter(
                    Appointment.tenant_id == tenant.id,
                    Appointment.status == "agendado"
                ).order_by(Appointment.id.desc()).first()

            if not current_apt:
                print(f"{RED}❌ No hay turnos agendados en el escenario. Ejecutá la opción [2] primero.{RESET}")
                continue

            print(f"\n⏳ {YELLOW}Ejecutando cancelación y activando Lista de Espera autónoma...{RESET}")
            res = await execute_cancellation_step(db, current_apt.id, reason="Imprevisto laboral de último momento")
            
            db.refresh(current_apt)
            current_wl = db.query(WaitlistEntry).filter(
                WaitlistEntry.tenant_id == tenant.id,
                WaitlistEntry.offered_appointment_id == current_apt.id
            ).first()

            print_status_box(
                "⚠️ CANCELACIÓN PROCESADA & RESCATE ACTIVADO",
                [
                    f"• Turno #{current_apt.id} marcado como 'cancelado'.",
                    f"• Alerta de Cancelación despachada a +{doctor_phone}.",
                    f"• Paciente ofrecido: '{res.get('candidate_offered')}' (+{waitlist_phone}).",
                    f"• Mensaje interactivo enviado a Laura con botones: [TOMAR TURNO] y [NO, PASO]."
                ],
                YELLOW
            )
            display_live_database(db, tenant.id)

        elif choice == "4":
            # Simulate Reject ("NO, PASO")
            if not current_apt or not current_wl:
                current_wl = db.query(WaitlistEntry).filter(
                    WaitlistEntry.tenant_id == tenant.id,
                    WaitlistEntry.status == "notificado_oferta"
                ).order_by(WaitlistEntry.id.desc()).first()
                if current_wl:
                    current_apt = db.query(Appointment).filter(Appointment.id == current_wl.offered_appointment_id).first()

            if not current_apt or not current_wl:
                print(f"{RED}❌ No hay oferta de turno pendiente para rechazar. Ejecutá [2] y [3] primero.{RESET}")
                continue

            print(f"\n⏳ {MAGENTA}Simulando paciente tocando 'NO, PASO' en WhatsApp...{RESET}")
            await execute_reject_step(db, current_apt.id, current_wl.id)
            db.refresh(current_wl)

            print_status_box(
                "🙅 RECHAZO CORDIAL PROCESADO ('NO, PASO')",
                [
                    f"• Laura Benítez declinó la oferta para las 17:00 hs.",
                    f"• Sofía le respondió con calidez rioplatense tranquilizadora:",
                    f"  '¡Dale, no te preocupes Laura! Tu lugar en lista de espera se mantiene...'",
                    f"• Estado en BD: 'rechazado' para este hueco, lista de espera protegida.",
                    f"• Sofía pasa inmediatamente a ofrecer el hueco al siguiente en fila."
                ],
                MAGENTA
            )
            display_live_database(db, tenant.id)

        elif choice == "5":
            # Simulate Claim ("TOMAR TURNO")
            if not current_apt or not current_wl:
                current_wl = db.query(WaitlistEntry).filter(
                    WaitlistEntry.tenant_id == tenant.id,
                    WaitlistEntry.status.in_(["notificado_oferta", "activa"])
                ).order_by(WaitlistEntry.id.desc()).first()
                if current_wl:
                    current_apt = db.query(Appointment).filter(
                        Appointment.tenant_id == tenant.id,
                        Appointment.status.in_(["cancelado", "agendado"])
                    ).order_by(Appointment.id.desc()).first()

            if not current_apt or not current_wl:
                print(f"{RED}❌ No hay ninguna oferta de turno pendiente para tomar. Ejecutá [2] y [3] primero.{RESET}")
                continue

            print(f"\n⏳ {GREEN}Simulando paciente tocando 'TOMAR TURNO' en WhatsApp...{RESET}")
            success = await execute_claim_step(db, current_apt.id, current_wl.id)

            if success:
                db.refresh(current_apt)
                date_str = current_apt.appointment_date.strftime("%d/%m a las %H:%M hs")
                print_status_box(
                    "🎉 ¡TURNO RESCATADO CON ÉXITO!",
                    [
                        f"• Turno de las {date_str} reasignado a '{current_wl.patient_name}'.",
                        f"• Estado en BD: 'rellenado_con_exito'.",
                        f"• Confirmación oficial enviada al WhatsApp de Laura.",
                        f"• ALERTA TRIUNFAL enviada al Doctor: 'Cero pérdida de facturación'."
                    ],
                    GREEN
                )
                display_live_database(db, tenant.id)
            else:
                print(f"{RED}❌ No se pudo completar la asignación del turno.{RESET}")

        elif choice == "6":
            # Guided show mode
            print(f"\n{CYAN}{BOLD}🎬 INICIANDO MODO SHOW EN VIVO PASO A PASO...{RESET}")
            print(f"Ideal para Google Meet: presioná [ENTER] en cada paso para guiar el relato.\n")

            clean_demo_scenario(db, tenant.id)
            display_live_database(db, tenant.id)
            input(f"{BOLD}👉 Mostrá la base de datos limpia al cliente y presioná [ENTER] para que el paciente agende solo...{RESET}")

            # Paso 1: Agendamiento autónomo
            print(f"\n{GREEN}▶ PASO 1 (Autogestión de Entrada):{RESET}")
            current_apt = await simulate_autonomous_booking_step(
                db=db,
                tenant_id=tenant.id,
                patient_name=patient_name,
                patient_phone=patient_phone,
                doctor_name=f"{doctor_name} - Odontología"
            )
            # Add Laura to waitlist
            current_wl = WaitlistEntry(
                tenant_id=tenant.id,
                patient_name=waitlist_name,
                patient_phone="".join(filter(str.isdigit, waitlist_phone)),
                doctor_or_service=f"{doctor_name} - Odontología",
                preferred_time_range="Por la tarde",
                status="activa"
            )
            db.add(current_wl)
            db.commit()
            db.refresh(current_wl)

            date_str = current_apt.appointment_date.strftime("%d/%m a las %H:%M hs")
            print(f"  El paciente {patient_name} agendó por WhatsApp hoy a las {date_str}.")
            print(f"  Alerta médica de nuevo turno recibida en el celular del Dr. Rossi (+{doctor_phone}).")
            display_live_database(db, tenant.id)
            input(f"\n{BOLD}👉 Explicá la alerta médica y presioná [ENTER] para simular la cancelación inesperada...{RESET}")

            # Paso 2: Cancelación
            print(f"\n{YELLOW}▶ PASO 2 (El Problema - Turno Cancelado):{RESET}")
            res = await execute_cancellation_step(db, current_apt.id, reason="Imprevisto personal de último momento")
            print(f"  🚨 {patient_name} acaba de cancelar su turno de las {date_str}.")
            print(f"  📲 Alerta de cancelación enviada al Doctor (+{doctor_phone}).")
            print(f"  🚀 Sofía le acaba de enviar la oferta con botones a {waitlist_name} (+{waitlist_phone}).")
            display_live_database(db, tenant.id)
            input(f"\n{BOLD}👉 Mostrá los botones interactivos en el celular de Laura y presioná [ENTER] para que acepte...{RESET}")

            # Paso 3: Aceptación
            print(f"\n{GREEN}▶ PASO 3 (La Solución - Rescate Autónomo):{RESET}")
            await execute_claim_step(db, current_apt.id, current_wl.id)
            print(f"  🎉 {waitlist_name} aceptó el turno.")
            print(f"  ✅ Turno confirmado y reasignado en la agenda en la fila #{current_apt.id}.")
            print(f"  💰 Alerta de Facturación Protegida recibida en el celular del Doctor.")
            display_live_database(db, tenant.id)
            print(f"\n{GREEN}{BOLD}✨ Fin del Show: El cliente vio el ciclo completo (Agendamiento -> Cancelación -> Rescate) en tiempo real.{RESET}\n")

        elif choice == "7":
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

        elif choice == "8":
            clean_demo_scenario(db, tenant.id)
            current_apt = None
            current_wl = None
            print(f"\n{GREEN}🧹 Escenario limpiado. Base de datos sin turnos de demo.{RESET}\n")
            display_live_database(db, tenant.id)

    db.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Sofía AI Agency — Live Healthcare Demo Runner")
    parser.add_argument("--setup", action="store_true", help="Only setup the demo scene and exit")
    parser.add_argument("--book", action="store_true", help="Simulate autonomous booking and exit")
    parser.add_argument("--cancel", action="store_true", help="Simulate cancellation for active demo appointment")
    parser.add_argument("--claim", action="store_true", help="Simulate claim for offered waitlist entry")
    parser.add_argument("--reject", action="store_true", help="Simulate rejection for offered waitlist entry")
    parser.add_argument("--view-db", action="store_true", help="Display live database tables and exit")
    parser.add_argument("--clean", action="store_true", help="Clean up demo scenario and exit")
    parser.add_argument("--doctor-phone", type=str, default="5493434536447", help="Doctor notification phone")
    parser.add_argument("--doctor-name", type=str, default="Dr. Pablo Rossi", help="Doctor name")
    parser.add_argument("--clinic-name", type=str, default="Consultorios Médicos San Martín (Demo)", help="Clinic name")
    parser.add_argument("--patient-phone", type=str, default="5491145678901", help="Patient phone")
    parser.add_argument("--waitlist-phone", type=str, default="5493435730520", help="Waitlist candidate phone")
    parser.add_argument("--non-interactive", action="store_true", help="Run without user prompts (for tests/automation)")
    return parser.parse_args()


async def main():
    args = parse_args()

    if args.non_interactive or args.setup or args.cancel or args.claim or args.reject or args.book or args.view_db or args.clean:
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

        if args.book:
            apt = await simulate_autonomous_booking_step(
                db=db,
                tenant_id=tenant.id,
                patient_name="Martín Gómez",
                patient_phone=args.patient_phone,
                doctor_name=f"{args.doctor_name} - Odontología"
            )
            print(f"✅ Booking executed: Apt #{apt.id} for {apt.patient_name}")

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

        if args.reject:
            wl = db.query(WaitlistEntry).filter(
                WaitlistEntry.tenant_id == tenant.id,
                WaitlistEntry.status == "notificado_oferta"
            ).order_by(WaitlistEntry.id.desc()).first()
            if wl and wl.offered_appointment_id:
                success = await execute_reject_step(db, wl.offered_appointment_id, wl.id)
                print(f"✅ Rejection executed: {success}")
            else:
                print("❌ No pending offer to reject.")

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

        if args.view_db:
            display_live_database(db, tenant.id)

        db.close()
        return

    # Interactive Wizard Mode
    await run_interactive_wizard()


if __name__ == "__main__":
    asyncio.run(main())
