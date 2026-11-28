from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class ActualizadorLead(Base):
    """
    Registro comercial y de candado para clientes de Súper Actualizador PRO.
    Almacena los leads que activan la demo de 7 días para seguimiento de ventas
    y previene abusos de demos repetidas en la misma PC.
    """
    __tablename__ = "actualizador_leads"

    id = Column(Integer, primary_key=True, index=True)
    hardware_id = Column(String, unique=True, index=True, nullable=False)
    comercio = Column(String, index=True, nullable=True)
    whatsapp = Column(String, index=True, nullable=True)
    email = Column(String, nullable=True)
    tipo_licencia = Column(String, default="DEMO_7_DIAS")  # DEMO_7_DIAS, FULL_PRO, BASE, ASISTENCIA_TECNICA
    clave_licencia = Column(Text, nullable=True)
    dias_demo = Column(Integer, default=7)
    demo_solicitada_at = Column(DateTime, default=utc_now)
    vence_at = Column(DateTime, nullable=True)
    ip_origen = Column(String, nullable=True)
    activo = Column(Boolean, default=True)
    notas = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class ActualizadorDownloadLog(Base):
    """
    Contador de descargas oficiales del paquete ZIP Súper Actualizador PRO.
    Registra fecha, IP y dispositivo para telemetría comercial en tiempo real.
    """
    __tablename__ = "actualizador_downloads"

    id = Column(Integer, primary_key=True, index=True)
    ip = Column(String, index=True, nullable=True)
    user_agent = Column(String, nullable=True)
    is_bot = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)
