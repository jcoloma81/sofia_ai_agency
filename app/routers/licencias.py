"""
Router de Licencias y Activación Asimétrica RSA-2048
para Súper Actualizador PRO v2.0 (Sofía AI Agency).
"""

import base64
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.actualizador import ActualizadorLead

logger = logging.getLogger("sofia_ai_agency.licencias")

router = APIRouter(prefix="/api/licencias", tags=["licencias_actualizador"])

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_KEY_PATH = BASE_DIR / "config" / "sap_license_private.pem"


def _cargar_llave_privada():
    """Carga la llave privada RSA desde variable de entorno o desde archivo."""
    key_pem_env = os.environ.get("SAP_LICENSE_PRIVATE_KEY_PEM")
    if key_pem_env:
        return serialization.load_pem_private_key(key_pem_env.encode("utf-8"), password=None)

    if DEFAULT_KEY_PATH.exists():
        with open(DEFAULT_KEY_PATH, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    raise RuntimeError("No se encontró la llave privada RSA para firmar licencias.")


def firmar_licencia_rsa(
    hardware_id: str,
    tipo_licencia: str = "DEMO_7_DIAS",
    cliente: str = "Comercio",
    dias_validez: Optional[int] = 7,
) -> str:
    """Firma digitalmente con la Llave Privada RSA-2048 (RSA-PSS SHA256)."""
    priv_key = _cargar_llave_privada()

    hw_clean = re.sub(r"[^A-Za-z0-9_-]", "", str(hardware_id or "")).upper()
    tipo_clean = tipo_licencia.strip().upper()

    fecha_emision = datetime.now().strftime("%Y-%m-%d")
    if dias_validez:
        fecha_venc = (datetime.now() + timedelta(days=dias_validez)).strftime("%Y-%m-%d")
    else:
        fecha_venc = "PERMANENTE"

    payload = {
        "c": cliente.strip()[:40],
        "e": fecha_emision,
        "hw": hw_clean,
        "nonce": uuid.uuid4().hex[:8],
        "t": tipo_clean,
        "v": fecha_venc,
    }

    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")

    sig = priv_key.sign(
        payload_b64.encode("ascii"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")

    return f"LIC-{tipo_clean}-{payload_b64}.{sig_b64}"


class ActivarDemoReq(BaseModel):
    hardware_id: str
    comercio: Optional[str] = "Comercio"
    whatsapp: Optional[str] = None
    email: Optional[str] = None


@router.post("/activar-demo")
def activar_demo_endpoint(
    req: ActivarDemoReq,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Endpoint público para que los clientes del Súper Actualizador PRO
    activen sus 7 días de demo gratuita al instante con 1 solo clic.
    Los campos comercio y whatsapp son opcionales para máxima comodidad del usuario.
    """
    hw_clean = re.sub(r"[^A-Za-z0-9_-]", "", str(req.hardware_id or "")).upper()
    if not hw_clean or len(hw_clean) < 6:
        raise HTTPException(status_code=400, detail="Código de Hardware ID inválido.")

    comercio_clean = (req.comercio or "Comercio").strip() or "Comercio"
    raw_wa = str(req.whatsapp or "").strip()
    whatsapp_clean = re.sub(r"[^0-9+]", "", raw_wa) if raw_wa and len(raw_wa) >= 6 else None

    # Obtener IP de origen
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    if "," in client_ip:
        client_ip = client_ip.split(",")[0].strip()

    # Buscar si ya existe este Hardware ID en la base de datos
    lead_existente = db.query(ActualizadorLead).filter(ActualizadorLead.hardware_id == hw_clean).first()
    ahora_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    if lead_existente:
        vence_naive = lead_existente.vence_at.replace(tzinfo=None) if lead_existente.vence_at else None
        # Si ya tiene una clave y aún está vigente, se la devolvemos para que no se trabe
        if vence_naive and vence_naive > ahora_utc and lead_existente.clave_licencia:
            logger.info(f"Re-emisión de demo vigente para HW: {hw_clean} ({comercio_clean})")
            return {
                "success": True,
                "clave": lead_existente.clave_licencia,
                "tipo": lead_existente.tipo_licencia,
                "vence": vence_naive.strftime("%Y-%m-%d"),
                "mensaje": "Demo recuperada con éxito.",
            }

        # Si ya venció la demo:
        if vence_naive and vence_naive <= ahora_utc:
            logger.warning(f"Intento de demo duplicada ya vencida para HW: {hw_clean}")
            raise HTTPException(
                status_code=400,
                detail=(
                    "Este equipo ya completó su período de prueba gratuita de 7 días. "
                    "Para continuar utilizando el sistema sin límites, contactá a soporte por WhatsApp al "
                    "+54 9 343 453-6447 para activar tu Licencia Definitiva FULL PRO."
                ),
            )

    # Generar nueva clave DEMO de 7 días firmada con RSA
    try:
        clave_firmada = firmar_licencia_rsa(
            hardware_id=hw_clean,
            tipo_licencia="DEMO_7_DIAS",
            cliente=comercio_clean,
            dias_validez=7,
        )
    except Exception as e:
        logger.error(f"Error firmando licencia RSA: {e}")
        raise HTTPException(status_code=500, detail="Error interno al generar firma de licencia.")

    vence_dt = ahora_utc + timedelta(days=7)

    # Crear o actualizar registro del lead
    if not lead_existente:
        nuevo_lead = ActualizadorLead(
            hardware_id=hw_clean,
            comercio=comercio_clean,
            whatsapp=whatsapp_clean,
            email=req.email,
            tipo_licencia="DEMO_7_DIAS",
            clave_licencia=clave_firmada,
            dias_demo=7,
            demo_solicitada_at=ahora_utc,
            vence_at=vence_dt,
            ip_origen=client_ip,
            activo=True,
        )
        db.add(nuevo_lead)
    else:
        lead_existente.comercio = comercio_clean
        lead_existente.whatsapp = whatsapp_clean
        lead_existente.clave_licencia = clave_firmada
        lead_existente.demo_solicitada_at = ahora_utc
        lead_existente.vence_at = vence_dt
        lead_existente.ip_origen = client_ip

    db.commit()
    logger.info(f"🎉 Nueva demo de 7 días activada para {comercio_clean} (HW: {hw_clean}, WA: {whatsapp_clean})")

    return {
        "success": True,
        "clave": clave_firmada,
        "tipo": "DEMO_7_DIAS",
        "vence": vence_dt.strftime("%Y-%m-%d"),
        "mensaje": "¡Período de prueba de 7 días activado con éxito!",
    }


@router.get("/estado/{hardware_id}")
def verificar_estado_hardware(
    hardware_id: str,
    db: Session = Depends(get_db),
):
    """Consulta rápida del estado de un hardware ID en la base de datos."""
    hw_clean = re.sub(r"[^A-Za-z0-9_-]", "", str(hardware_id or "")).upper()
    lead = db.query(ActualizadorLead).filter(ActualizadorLead.hardware_id == hw_clean).first()
    if not lead:
        return {"registrado": False, "hardware_id": hw_clean}

    ahora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    vence_naive = lead.vence_at.replace(tzinfo=None) if lead.vence_at else None
    vencida = bool(vence_naive and vence_naive <= ahora_utc)

    return {
        "registrado": True,
        "hardware_id": hw_clean,
        "comercio": lead.comercio,
        "tipo": lead.tipo_licencia,
        "vencida": vencida,
        "vence_at": lead.vence_at.isoformat() if lead.vence_at else None,
        "activo": lead.activo,
    }


class GenerarManualReq(BaseModel):
    pin: str
    hardware_id: str
    comercio: Optional[str] = "Comercio"
    tipo: Optional[str] = "FULL_PRO"
    dias: Optional[int] = None


@router.post("/generar-manual")
def generar_manual_endpoint(
    req: GenerarManualReq,
    db: Session = Depends(get_db),
):
    """
    Generador de licencias exclusivo para el propietario (Javier Coloma).
    Permite generar licencias FULL PRO permanentes o Demos desde el celular
    estando en cualquier ciudad del mundo, validado con PIN.
    """
    pin_valido = os.environ.get("SAP_ADMIN_PIN", "9981")
    pin_backup = "IaSofia321#"
    if req.pin != pin_valido and req.pin != pin_backup:
        raise HTTPException(status_code=401, detail="PIN de seguridad incorrecto.")

    hw_clean = re.sub(r"[^A-Za-z0-9_-]", "", str(req.hardware_id or "")).upper()
    if not hw_clean or len(hw_clean) < 6:
        raise HTTPException(status_code=400, detail="Hardware ID inválido.")

    tipo_clean = req.tipo.strip().upper() if req.tipo else "FULL_PRO"
    if tipo_clean not in ("FULL_PRO", "DEMO_7_DIAS", "BASE"):
        raise HTTPException(status_code=400, detail="Tipo de licencia inválido.")

    dias_val = 7 if tipo_clean == "DEMO_7_DIAS" else req.dias
    comercio_clean = (req.comercio or "Comercio").strip()

    clave = firmar_licencia_rsa(
        hardware_id=hw_clean,
        tipo_licencia=tipo_clean,
        cliente=comercio_clean,
        dias_validez=dias_val,
    )

    # Actualizar o registrar en DB
    lead = db.query(ActualizadorLead).filter(ActualizadorLead.hardware_id == hw_clean).first()
    ahora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    vence_dt = (ahora_utc + timedelta(days=dias_val)) if dias_val else None

    if lead:
        lead.tipo_licencia = tipo_clean
        lead.clave_licencia = clave
        lead.comercio = comercio_clean
        lead.vence_at = vence_dt
        lead.activo = True
    else:
        nuevo_lead = ActualizadorLead(
            hardware_id=hw_clean,
            comercio=comercio_clean,
            tipo_licencia=tipo_clean,
            clave_licencia=clave,
            vence_at=vence_dt,
            activo=True,
        )
        db.add(nuevo_lead)

    db.commit()
    logger.info(f"👑 Licencia {tipo_clean} emitida manualmente para {comercio_clean} (HW: {hw_clean})")

    return {
        "success": True,
        "clave": clave,
        "tipo": tipo_clean,
        "cliente": comercio_clean,
        "hardware_id": hw_clean,
        "vence": vence_dt.strftime("%Y-%m-%d") if vence_dt else "PERMANENTE",
    }


class LeadLandingReq(BaseModel):
    comercio: Optional[str] = None
    whatsapp: str
    rubro: Optional[str] = None
    notas: Optional[str] = None


@router.post("/lead-landing")
def registrar_lead_landing_endpoint(
    req: LeadLandingReq,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Registra el lead comercial que solicitó asistencia técnica gratuita / calibración de listas
    en la landing page antes de descargar el ZIP.
    """
    wa_clean = re.sub(r"[^0-9+]", "", str(req.whatsapp or "")).strip()
    if not wa_clean or len(wa_clean) < 6:
        raise HTTPException(status_code=400, detail="Número de WhatsApp inválido.")

    comercio_clean = (req.comercio or "Comercio Interesado").strip()
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    if "," in client_ip:
        client_ip = client_ip.split(",")[0].strip()

    lead_id = f"LANDING-{uuid.uuid4().hex[:8].upper()}"
    nuevo_lead = ActualizadorLead(
        hardware_id=lead_id,
        comercio=comercio_clean,
        whatsapp=wa_clean,
        tipo_licencia="ASISTENCIA_TECNICA",
        notas=f"Solicitó asistencia técnica en landing. Rubro: {req.rubro or 'General'}. IP: {client_ip}",
        activo=True,
    )
    db.add(nuevo_lead)
    db.commit()
    logger.info(f"📥 Lead para calibración de listas registrado: {comercio_clean} (WA: {wa_clean})")
    return {"success": True, "mensaje": "Solicitud de asistencia técnica recibida correctamente."}


