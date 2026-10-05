import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.tenant import Tenant, Appointment, WaitlistEntry, MembershipPayment, InactiveCustomer, TenantSession
from app.services.tenant_service import tenant_service
from app.services.appointment_service import appointment_service
from app.services.billing_service import billing_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants", tags=["Enterprise Multi-Tenant"])

class TenantCreateSchema(BaseModel):
    slug: str
    name: str
    business_type: str
    owner_phone: str
    owner_name: Optional[str] = None
    logo_url: Optional[str] = None
    branding_header: Optional[str] = None
    deep_link_keyword: Optional[str] = None
    modules_enabled: Optional[List[str]] = ["turnos_rellena_huecos", "recordatorios", "faq"]
    knowledge_base: Optional[Dict[str, Any]] = {}

@router.get("/")
def list_tenants(db: Session = Depends(get_db)):
    tenants = db.query(Tenant).filter(Tenant.active == True).all()
    res = []
    for t in tenants:
        res.append({
            "id": t.id,
            "slug": t.slug,
            "name": t.name,
            "business_type": t.business_type,
            "owner_phone": t.owner_phone,
            "owner_name": t.owner_name,
            "deep_link_keyword": t.deep_link_keyword,
            "modules": json.loads(t.modules_enabled or "[]"),
            "appointments_count": len(t.appointments),
            "memberships_count": len(t.memberships),
            "waitlist_count": len(t.waitlist_entries),
            "inactive_count": len(t.inactive_customers)
        })
    return {"status": "success", "count": len(res), "tenants": res}

@router.post("/")
def create_tenant(payload: TenantCreateSchema, db: Session = Depends(get_db)):
    clean_slug = payload.slug.lower().strip()
    existing = db.query(Tenant).filter(Tenant.slug == clean_slug).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"El tenant '{clean_slug}' ya existe.")

    tenant = Tenant(
        slug=clean_slug,
        name=payload.name.strip(),
        business_type=payload.business_type.lower().strip(),
        owner_phone="".join(filter(str.isdigit, payload.owner_phone)),
        owner_name=payload.owner_name,
        logo_url=payload.logo_url,
        branding_header=payload.branding_header,
        deep_link_keyword=payload.deep_link_keyword or clean_slug,
        modules_enabled=json.dumps(payload.modules_enabled or ["faq"]),
        knowledge_base=json.dumps(payload.knowledge_base or {}, ensure_ascii=False),
        active=True
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return {"status": "success", "message": f"Tenant '{tenant.name}' creado exitosamente.", "tenant_id": tenant.id}

@router.post("/seed-demo")
def seed_demo_tenants(db: Session = Depends(get_db)):
    """
    Seeds ready-to-sell enterprise demo businesses:
    1. Consultorios Odontológicos Alvear (Salud / Turnero + Rellena-Huecos)
    2. Iron Gym Paraná (Gimnasio / Cobranzas Mercado Pago + Promo Verano)
    3. Óptica Visión (Comercio / Chequeos visuales + Reactivador de Dormidos)
    4. Taller Mecánico El Rafa (Oficios / Presupuestos con fotos y Services preventivos)
    """
    now = datetime.now(timezone.utc)
    seeded = []

    # 1. Consultorios Odontológicos Alvear
    t1 = db.query(Tenant).filter(Tenant.slug == "clinica_alvear").first()
    if not t1:
        t1 = Tenant(
            slug="clinica_alvear",
            name="Consultorios Odontológicos Alvear",
            business_type="salud",
            owner_phone="5493434536447",
            owner_name="Dra. Silvina Gómez",
            logo_url="https://images.unsplash.com/photo-1629909613654-28e377c37b09?w=600&auto=format&fit=crop",
            branding_header="🏥 *CONSULTORIOS ODONTOLÓGICOS ALVEAR*\n_Central de Turnos y Gestión Profesional_",
            deep_link_keyword="Clinica_Alvear",
            modules_enabled=json.dumps(["turnos_rellena_huecos", "recordatorios", "faq"]),
            knowledge_base=json.dumps({
                "direccion": "Calle Alvear 450, Paraná, Entre Ríos",
                "horarios": "Lunes a Viernes de 8:00 a 20:00 hs. Sábados de 9:00 a 13:00 hs.",
                "profesionales": [
                    {"nombre": "Dra. Silvina Gómez", "especialidad": "Odontología Integral y Blanqueamiento"},
                    {"nombre": "Dr. Juan Carlos Pérez", "especialidad": "Implantes y Cirugía Maxilofacial"}
                ],
                "obras_sociales": "Iosper (con bono), Osde, Swiss Medical, Galeno. Particulares con 20% de reintegro en efectivo.",
                "faq": "Urgencias dentales se atienden por orden de llegada previa confirmación telefónica."
            }, ensure_ascii=False)
        )
        db.add(t1)
        db.commit()
        db.refresh(t1)

        # Seed sample appointments
        apt1 = Appointment(
            tenant_id=t1.id,
            patient_name="María Gómez",
            patient_phone="5493434556677",
            doctor_or_service="Dra. Silvina Gómez - Control Odontológico",
            appointment_date=now + timedelta(hours=24),
            status="agendado"
        )
        apt2 = Appointment(
            tenant_id=t1.id,
            patient_name="Carlos Bianchi",
            patient_phone="5493434998811",
            doctor_or_service="Dr. Juan Carlos Pérez - Consulta Implantes",
            appointment_date=now + timedelta(hours=48),
            status="agendado"
        )
        db.add_all([apt1, apt2])

        # Seed sample waitlist candidates
        wl1 = WaitlistEntry(
            tenant_id=t1.id,
            patient_name="Laura Santillán",
            patient_phone="5493434123456",
            doctor_or_service="Dra. Silvina Gómez",
            preferred_time_range="Tardes después de las 15hs",
            status="activa"
        )
        wl2 = WaitlistEntry(
            tenant_id=t1.id,
            patient_name="Martín Benítez",
            patient_phone="5493434654321",
            doctor_or_service="Dra. Silvina Gómez",
            preferred_time_range="Cualquier horario mañana",
            status="activa"
        )
        db.add_all([wl1, wl2])
        db.commit()
        seeded.append("clinica_alvear")

    # 2. Iron Gym Paraná
    t2 = db.query(Tenant).filter(Tenant.slug == "iron_gym").first()
    if not t2:
        t2 = Tenant(
            slug="iron_gym",
            name="Iron Gym Paraná",
            business_type="gimnasio",
            owner_phone="5493434536447",
            owner_name="Marcos Titán",
            logo_url="https://images.unsplash.com/photo-1534438327276-14e5300c3a48?w=600&auto=format&fit=crop",
            branding_header="🏋️ *IRON GYM PARANÁ*\n_Administración y Pases de Entrenamiento_",
            deep_link_keyword="Iron_Gym",
            modules_enabled=json.dumps(["cobranzas_mp", "reactivador", "faq"]),
            knowledge_base=json.dumps({
                "direccion": "Av. Ramírez 1240, Paraná",
                "horarios": "Lunes a Viernes de 6:30 a 22:30 hs continuado. Sábados de 8:00 a 14:00 hs.",
                "planes": {
                    "musculacion_3_dias": {"precio": 24000, "detalle": "3 veces por semana con rutina personalizada"},
                    "pase_libre": {"precio": 31000, "detalle": "Acceso total sin límite de días ni horarios + clases"},
                    "cross_training": {"precio": 28000, "detalle": "Clases grupales con coach certificado"}
                },
                "politica_cobro": "Las cuotas vencen del 1 al 10 de cada mes. A partir del día 11 rige un 10% de recargo administrativo.",
                "alias_cbu": "irongym.parana.mp",
                "promo_verano": "Abonando 2 meses de Pase Libre, el 3er mes es 100% BONIFICADO."
            }, ensure_ascii=False)
        )
        db.add(t2)
        db.commit()
        db.refresh(t2)

        # Seed sample memberships
        mem1 = MembershipPayment(
            tenant_id=t2.id,
            member_name="Lucas Martínez",
            member_phone="5493434112233",
            plan_name="Pase Libre Musculación",
            amount=31000.0,
            due_date=now + timedelta(days=2),
            mp_payment_link="https://mpago.la/pos/iron_gym/31000",
            payment_status="pendiente"
        )
        mem2 = MembershipPayment(
            tenant_id=t2.id,
            member_name="Federico Rossi",
            member_phone="5493434223344",
            plan_name="Musculación 3 Días",
            amount=24000.0,
            due_date=now - timedelta(days=3),
            mp_payment_link="https://mpago.la/pos/iron_gym/24000",
            payment_status="pendiente"
        )
        db.add_all([mem1, mem2])

        # Seed dormant customers (ex-socios)
        dormant1 = InactiveCustomer(
            tenant_id=t2.id,
            customer_name="Agustín Morales",
            customer_phone="5493434990011",
            service_or_product="Pase Libre (Inactivo hace 75 días)",
            campaign_name="promo_verano",
            status="dormido"
        )
        dormant2 = InactiveCustomer(
            tenant_id=t2.id,
            customer_name="Camila Valenzuela",
            customer_phone="5493434990022",
            service_or_product="Cross Training (Inactiva hace 90 días)",
            campaign_name="promo_verano",
            status="dormido"
        )
        db.add_all([dormant1, dormant2])
        db.commit()
        seeded.append("iron_gym")

    # 3. Óptica Visión
    t3 = db.query(Tenant).filter(Tenant.slug == "optica_vision").first()
    if not t3:
        t3 = Tenant(
            slug="optica_vision",
            name="Óptica Visión Central",
            business_type="optica",
            owner_phone="5493434536447",
            owner_name="Martín Viale",
            logo_url="https://images.unsplash.com/photo-1591076482161-42ce6da69f67?w=600&auto=format&fit=crop",
            branding_header="👓 *ÓPTICA VISIÓN CENTRAL*\n_Salud Visual y Asesoramiento Técnico_",
            deep_link_keyword="Optica_Vision",
            modules_enabled=json.dumps(["reactivador", "faq"]),
            knowledge_base=json.dumps({
                "direccion": "Calle Urquiza 820, Paraná",
                "horarios": "Lunes a Viernes de 8:30 a 12:30 y de 16:30 a 20:30 hs. Sábados de 9:00 a 13:00 hs.",
                "servicios": "Armazones de diseño, cristales multifocales, filtro de luz azul (Blue Light Cut), lentes de contacto blandas y descartables.",
                "obras_sociales": "Convenios directos con Iosper, Osde, Swiss Medical, PAMI (recetas oficiales).",
                "beneficio_anual": "Control computarizado de agudeza visual sin costo para clientes registrados."
            }, ensure_ascii=False)
        )
        db.add(t3)
        db.commit()
        db.refresh(t3)

        dormant_opt1 = InactiveCustomer(
            tenant_id=t3.id,
            customer_name="Valeria Fontana",
            customer_phone="5493434771122",
            service_or_product="Cristales Antirréflex (Hace 12 meses)",
            campaign_name="renovacion_anual",
            status="dormido"
        )
        db.add(dormant_opt1)
        db.commit()
        seeded.append("optica_vision")

    return {
        "status": "success",
        "message": "Demo enterprise tenants successfully created or updated.",
        "seeded_tenants": seeded
    }

@router.post("/cron/run-appointment-reminders")
async def trigger_appointment_reminders(hours_ahead: int = Query(24), db: Session = Depends(get_db)):
    count = await appointment_service.scan_and_send_appointment_reminders(db, hours_ahead=hours_ahead)
    return {"status": "success", "reminders_sent": count}

@router.post("/cron/run-billing-reminders")
async def trigger_billing_reminders(db: Session = Depends(get_db)):
    count = await billing_service.scan_and_send_due_reminders(db)
    return {"status": "success", "billing_reminders_sent": count}

@router.post("/{slug}/reactivate")
async def trigger_tenant_reactivation(slug: str, promo_text: Optional[str] = None, db: Session = Depends(get_db)):
    res = await billing_service.run_dormant_reactivator_campaign(db, slug, promo_text)
    return res
