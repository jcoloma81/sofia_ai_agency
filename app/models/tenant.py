from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

def utc_now():
    return datetime.now(timezone.utc)

class Tenant(Base):
    """
    Enterprise Tenant Model:
    Represents an independent business, clinic, gym, or professional practice
    managed autonomously under Sofía's Single-Number Meta Cloud API architecture.
    """
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, index=True, nullable=False) # e.g. "clinica_alvear", "iron_gym"
    name = Column(String, nullable=False)                          # e.g. "Consultorios Odontológicos Alvear"
    business_type = Column(String, nullable=False, index=True)     # "salud", "gimnasio", "optica", "inmobiliaria", "taller", "comercio"
    owner_phone = Column(String, index=True, nullable=False)       # e.g. "5493434536447" (Owner/Doctor notification recipient)
    owner_name = Column(String, nullable=True)                     # e.g. "Dra. Silvina Gómez"
    owner_email = Column(String, index=True, nullable=True)        # e.g. "doctor@miclinica.com" (Backup notifications via email)
    logo_url = Column(String, nullable=True)                       # Public URL of the HD logo/banner image
    branding_header = Column(Text, nullable=True)                  # Formatted header text prepended to outbound messages
    deep_link_keyword = Column(String, unique=True, index=True)    # e.g. "Clinica_Alvear", "Iron_Gym" (case-insensitive)
    modules_enabled = Column(Text, default='["faq"]')              # JSON array: ["turnos_rellena_huecos", "recordatorios", "cobranzas_mp", "reactivador", "faq"]
    knowledge_base = Column(Text, default='{}')                    # JSON or rich text containing services, prices, schedules, FAQs, rules
    # Plan & Messaging Quota Architecture ($30.000 ARS Policy)
    plan_type = Column(String, default="shared", index=True)       # "shared" ($30k setup, 150 msgs) or "enterprise" ($95k setup, dedicated line, unlimited)
    monthly_message_quota = Column(Integer, default=150)           # 150 msgs on shared, 999999 on enterprise
    messages_sent_this_month = Column(Integer, default=0)
    extra_messages_balance = Column(Integer, default=0)            # Extra messages purchased via Mercado Pago
    quota_exhausted_alert_sent = Column(Boolean, default=False)    # Prevents alert spam when quota is reached
    last_quota_reset = Column(DateTime, default=utc_now)

    active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    appointments = relationship("Appointment", back_populates="tenant", cascade="all, delete-orphan")
    waitlist_entries = relationship("WaitlistEntry", back_populates="tenant", cascade="all, delete-orphan")
    memberships = relationship("MembershipPayment", back_populates="tenant", cascade="all, delete-orphan")
    inactive_customers = relationship("InactiveCustomer", back_populates="tenant", cascade="all, delete-orphan")
    pack_payments = relationship("MessagePackPayment", back_populates="tenant", cascade="all, delete-orphan")

class TenantSession(Base):
    """
    Maps an incoming patient/client phone number to an active Tenant session.
    Allows a single Meta WhatsApp number to handle hundreds of businesses seamlessly.
    """
    __tablename__ = "tenant_sessions"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String, index=True, nullable=False)             # E.164 phone of customer
    tenant_slug = Column(String, ForeignKey("tenants.slug"), index=True, nullable=False)
    context_data = Column(Text, default="{}")                      # Transient state data (e.g. pending doctor selection)
    last_interaction = Column(DateTime, default=utc_now, index=True)
    created_at = Column(DateTime, default=utc_now)

class Appointment(Base):
    """
    Turno Médico / Cita Profesional with automated reminders and instant 'Rellena-Huecos'.
    """
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True, nullable=False)
    patient_name = Column(String, nullable=False)
    patient_phone = Column(String, index=True, nullable=False)
    doctor_or_service = Column(String, nullable=False)             # e.g. "Dra. Silvina Gómez - Odontología General"
    appointment_date = Column(DateTime, index=True, nullable=False)
    status = Column(String, default="agendado", index=True)         # "agendado", "recordatorio_48h", "recordatorio_24h", "confirmado", "cancelado", "rellenado_con_exito"
    reminder_sent_at = Column(DateTime, nullable=True)
    reminder_48h_sent_at = Column(DateTime, nullable=True)
    reminder_24h_sent_at = Column(DateTime, nullable=True)
    confirmation_received_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    tenant = relationship("Tenant", back_populates="appointments")

class WaitlistEntry(Base):
    """
    Active Waitlist: Candidates waiting for an earlier or open appointment slot.
    When someone cancels, Sofia offers the slot STRICTLY ONE-BY-ONE to avoid double booking.
    """
    __tablename__ = "waitlist_entries"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True, nullable=False)
    patient_name = Column(String, nullable=False)
    patient_phone = Column(String, index=True, nullable=False)
    doctor_or_service = Column(String, nullable=False)
    preferred_time_range = Column(String, nullable=True)           # e.g. "Por la tarde", "Cualquier horario mañana"
    status = Column(String, default="activa", index=True)          # "activa", "notificado_oferta", "turno_tomado", "rechazado", "expirada"
    offered_appointment_id = Column(Integer, nullable=True)
    offered_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)                   # Deadline to answer before passing to next candidate
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    tenant = relationship("Tenant", back_populates="waitlist_entries")

class MembershipPayment(Base):
    """
    Subscription & Fee Management for Gyms, Sports Clubs, Dance Academies, Institutes.
    Automates polite collection, Mercado Pago payment links, and receipt verification.
    """
    __tablename__ = "membership_payments"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True, nullable=False)
    member_name = Column(String, nullable=False)
    member_phone = Column(String, index=True, nullable=False)
    plan_name = Column(String, nullable=False)                     # e.g. "Pase Libre Musculación", "Inglés Niños 2"
    amount = Column(Float, nullable=False, default=0.0)
    due_date = Column(DateTime, index=True, nullable=False)        # Expiration date (e.g. 10th of current month)
    payment_status = Column(String, default="pendiente", index=True) # "pendiente", "aviso_enviado", "comprobante_enviado", "pagado", "vencido"
    mp_payment_link = Column(String, nullable=True)                # Mercado Pago dynamic or fixed link
    receipt_image_url = Column(String, nullable=True)              # Link or path to bank transfer screenshot
    last_reminder_sent_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    tenant = relationship("Tenant", back_populates="memberships")

class InactiveCustomer(Base):
    """
    Reactivador de Clientes Dormidos:
    Holds past customers (inactive > 60-90 days) ready for high-conversion reactivation campaigns.
    """
    __tablename__ = "inactive_customers"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True, nullable=False)
    customer_name = Column(String, nullable=False)
    customer_phone = Column(String, index=True, nullable=False)
    last_interaction_date = Column(DateTime, nullable=True)
    service_or_product = Column(String, nullable=True)             # e.g. "Pase Libre Verano", "Cristales Antirréflex", "Service 10.000km"
    campaign_name = Column(String, default="general", index=True)
    status = Column(String, default="dormido", index=True)         # "dormido", "contactado", "interesado", "reactivado", "no_interesado"
    contacted_at = Column(DateTime, nullable=True)
    response_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    tenant = relationship("Tenant", back_populates="inactive_customers")

class MessagePackPayment(Base):
    """
    Message Pack Recharges via Mercado Pago:
    Tracks purchases of extra outbound message packs (e.g. 100 msgs for $4.500 ARS).
    """
    __tablename__ = "message_pack_payments"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True, nullable=False)
    mp_preference_id = Column(String, index=True, nullable=True)
    mp_payment_id = Column(String, unique=True, index=True, nullable=True)
    external_reference = Column(String, unique=True, index=True, nullable=False)
    pack_name = Column(String, default="Pack 100 Mensajes Extra")
    pack_messages = Column(Integer, default=100)
    amount = Column(Float, default=4500.0)
    status = Column(String, default="pending", index=True) # "pending", "approved", "rejected"
    mp_init_point = Column(String, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    tenant = relationship("Tenant", back_populates="pack_payments")
