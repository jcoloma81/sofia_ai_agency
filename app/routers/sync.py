import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Union
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.tenant import Tenant, Appointment, MembershipPayment, InactiveCustomer
from app.models.prospect import MerchantProduct
from app.services.appointment_service import appointment_service
from app.services import whatsapp
from app.config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sync", tags=["Universal Multi-Industry Sync"])

def parse_argentine_datetime(date_str: str, time_str: Optional[str] = None) -> Optional[datetime]:
    """
    Parses date and time strings in common Argentine formats and converts to UTC (Argentina is UTC-3).
    Supports:
      - '16/10/2026 10:30', '16/10/2026', '2026-10-16 10:30', '16-10-2026', etc.
    """
    if not date_str:
        return None
    raw = str(date_str).strip()
    if time_str and str(time_str).strip():
        raw = f"{raw} {str(time_str).strip()}"

    # Try common formats
    formats = [
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d-%m-%Y"
    ]

    parsed_dt = None
    for fmt in formats:
        try:
            parsed_dt = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue

    if not parsed_dt:
        return None

    # If format was date-only, default time to 09:00 local
    if parsed_dt.hour == 0 and parsed_dt.minute == 0 and ("00:00" not in raw):
        parsed_dt = parsed_dt.replace(hour=9, minute=0)

    # Convert from Argentina local time (UTC-3) to UTC
    # e.g. 10:00 local + 3h = 13:00 UTC
    dt_utc = parsed_dt + timedelta(hours=3)
    return dt_utc.replace(tzinfo=timezone.utc)


class SyncBatchRequest(BaseModel):
    source: Optional[str] = "api"  # "google_sheets", "desktop_excel", "manual"
    rows: List[Dict[str, Any]]


@router.get("/{tenant_slug}/template")
def get_sync_template(tenant_slug: str, db: Session = Depends(get_db)):
    """
    Returns the expected columns and recommended template for a given tenant / vertical.
    """
    tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug.lower().strip()).first()
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_slug}' no encontrado.")

    templates = {
        "salud": {
            "columns": ["fecha", "hora", "paciente", "telefono", "profesional", "notas"],
            "example": [
                {"fecha": "16/10/2026", "hora": "10:30", "paciente": "Laura Benítez", "telefono": "5493434536447", "profesional": "Dr. González - Odontología", "notas": "Primera consulta"}
            ]
        },
        "gimnasio": {
            "columns": ["socio", "telefono", "plan", "vencimiento", "monto", "notas"],
            "example": [
                {"socio": "Lucas Pérez", "telefono": "5493434112233", "plan": "Musculación Pase Libre", "vencimiento": "10/11/2026", "monto": 25000, "notas": "Pago al día"}
            ]
        },
        "taller": {
            "columns": ["cliente", "telefono", "vehiculo_orden", "estado", "monto_saldo", "notas"],
            "example": [
                {"cliente": "Carlos Martínez", "telefono": "5493434778899", "vehiculo_orden": "Toyota Hilux AB123CD", "estado": "listo_para_retirar", "monto_saldo": 45000, "notas": "Service 10.000km"}
            ]
        },
        "optica": {
            "columns": ["cliente", "telefono", "trabajo_armazon", "estado", "monto_saldo", "notas"],
            "example": [
                {"cliente": "Valeria Fontana", "telefono": "5493434771122", "trabajo_armazon": "Cristales Antirréflex", "estado": "listo_para_retirar", "monto_saldo": 32000, "notas": "Armazón propio"}
            ]
        },
        "veterinaria": {
            "columns": ["dueno", "mascota", "telefono", "servicio_vacuna", "proxima_fecha", "notas"],
            "example": [
                {"dueno": "Ana Rodríguez", "mascota": "Toby", "telefono": "5493434665544", "servicio_vacuna": "Vacuna Séxtuple Canina", "proxima_fecha": "15/11/2026", "notas": "Revacunación anual"}
            ]
        },
        "comercio": {
            "columns": ["producto", "precio", "stock", "categoria", "notas"],
            "example": [
                {"producto": "Aceite Girasol 1.5L", "precio": 2400.0, "stock": 50, "categoria": "Almacén", "notas": "Precio mayorista"}
            ]
        }
    }

    business_type = tenant.business_type.lower()
    info = templates.get(business_type, templates["salud"])
    return {
        "status": "success",
        "tenant_slug": tenant.slug,
        "tenant_name": tenant.name,
        "business_type": business_type,
        "template": info
    }


@router.post("/{tenant_slug}")
async def sync_tenant_data(
    tenant_slug: str,
    payload: Union[SyncBatchRequest, List[Dict[str, Any]], Dict[str, Any]],
    db: Session = Depends(get_db)
):
    """
    Universal Multi-Industry Sync Endpoint:
    Accepts row batches from Google Sheets, Windows Desktop Excel Watcher, or direct APIs.
    Dispatches records to respective domain models (Appointments, Memberships, Orders, Products)
    with idempotency checks to avoid duplicate records.
    """
    tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug.lower().strip()).first()
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_slug}' no encontrado.")

    # Normalize payload into rows
    rows = []
    source = "api"
    if isinstance(payload, SyncBatchRequest):
        rows = payload.rows
        source = payload.source or "api"
    elif isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        if "rows" in payload and isinstance(payload["rows"], list):
            rows = payload["rows"]
            source = payload.get("source", "api")
        elif "values" in payload and isinstance(payload["values"], list):
            # Format from Google Sheets raw values [[headers], [row1], [row2]]
            raw_vals = payload["values"]
            if len(raw_vals) > 1:
                headers = [str(h).lower().strip() for h in raw_vals[0]]
                for r in raw_vals[1:]:
                    if any(r): # skip empty
                        row_dict = {}
                        for idx, h in enumerate(headers):
                            if idx < len(r):
                                row_dict[h] = r[idx]
                        rows.append(row_dict)
            source = "google_sheets"
        else:
            rows = [payload]

    if not rows:
        return {"status": "success", "message": "No se recibieron filas para sincronizar.", "count": 0}

    business_type = tenant.business_type.lower()
    created_count = 0
    updated_count = 0
    details = []

    for r in rows:
        # Normalize dictionary keys to lowercase and stripped
        clean_r = {str(k).lower().strip(): v for k, v in r.items() if v is not None}
        
        # -----------------------------------------------------------------
        # A. VERTICAL: SALUD & CONSULTORIOS (Appointments & Reminders)
        # -----------------------------------------------------------------
        if business_type in ["salud", "consultorio", "odontologia", "estetica"]:
            patient_name = clean_r.get("paciente") or clean_r.get("nombre") or clean_r.get("patient_name")
            phone_raw = clean_r.get("telefono") or clean_r.get("celular") or clean_r.get("whatsapp") or clean_r.get("phone")
            doctor_raw = clean_r.get("profesional") or clean_r.get("medico") or clean_r.get("doctor") or clean_r.get("doctor_or_service") or "Profesional de la Clínica"
            date_raw = clean_r.get("fecha") or clean_r.get("date")
            time_raw = clean_r.get("hora") or clean_r.get("horario") or clean_r.get("time")
            notes = clean_r.get("notas") or clean_r.get("motivo") or clean_r.get("notes") or f"Sincronizado vía {source}"

            if not patient_name or not phone_raw or not date_raw:
                continue

            dt_utc = parse_argentine_datetime(str(date_raw), str(time_raw) if time_raw else None)
            if not dt_utc:
                continue

            clean_phone = "".join(filter(str.isdigit, str(phone_raw)))
            if not clean_phone.startswith("54") and len(clean_phone) == 10:
                clean_phone = f"549{clean_phone}"

            # Idempotency check: look for existing appointment for same tenant + phone + date/hour
            existing = db.query(Appointment).filter(
                Appointment.tenant_id == tenant.id,
                Appointment.patient_phone == clean_phone,
                Appointment.appointment_date >= dt_utc - timedelta(minutes=15),
                Appointment.appointment_date <= dt_utc + timedelta(minutes=15)
            ).first()

            if existing:
                existing.patient_name = str(patient_name).strip()
                existing.doctor_or_service = str(doctor_raw).strip()
                if notes:
                    existing.notes = str(notes)
                updated_count += 1
                details.append(f"Turno actualizado: {patient_name} ({dt_utc.strftime('%d/%m %H:%M')} UTC)")
            else:
                apt = appointment_service.create_appointment(
                    db=db,
                    tenant_id=tenant.id,
                    patient_name=str(patient_name).strip(),
                    patient_phone=clean_phone,
                    doctor_or_service=str(doctor_raw).strip(),
                    appointment_date=dt_utc,
                    notes=str(notes)
                )
                created_count += 1
                details.append(f"Turno creado: {patient_name} ({dt_utc.strftime('%d/%m %H:%M')} UTC)")

        # -----------------------------------------------------------------
        # B. VERTICAL: GIMNASIOS & CLUBES (Memberships & Collections)
        # -----------------------------------------------------------------
        elif business_type in ["gimnasio", "club", "academia"]:
            member_name = clean_r.get("socio") or clean_r.get("nombre") or clean_r.get("member_name")
            phone_raw = clean_r.get("telefono") or clean_r.get("celular") or clean_r.get("whatsapp")
            plan_name = clean_r.get("plan") or clean_r.get("disciplina") or "Pase Libre"
            due_raw = clean_r.get("vencimiento") or clean_r.get("fecha_vencimiento") or clean_r.get("due_date")
            amount_raw = clean_r.get("monto") or clean_r.get("importe") or clean_r.get("precio") or 0.0

            if not member_name or not phone_raw:
                continue

            clean_phone = "".join(filter(str.isdigit, str(phone_raw)))
            if not clean_phone.startswith("54") and len(clean_phone) == 10:
                clean_phone = f"549{clean_phone}"

            due_utc = parse_argentine_datetime(str(due_raw)) if due_raw else (datetime.now(timezone.utc) + timedelta(days=10))
            try:
                clean_amount = float(str(amount_raw).replace("$", "").replace(".", "").replace(",", ".").strip())
            except Exception:
                clean_amount = 0.0

            existing_mem = db.query(MembershipPayment).filter(
                MembershipPayment.tenant_id == tenant.id,
                MembershipPayment.member_phone == clean_phone
            ).first()

            if existing_mem:
                existing_mem.member_name = str(member_name).strip()
                existing_mem.plan_name = str(plan_name).strip()
                existing_mem.amount = clean_amount
                if due_utc:
                    existing_mem.due_date = due_utc
                updated_count += 1
                details.append(f"Socio actualizado: {member_name} (${clean_amount})")
            else:
                mem = MembershipPayment(
                    tenant_id=tenant.id,
                    member_name=str(member_name).strip(),
                    member_phone=clean_phone,
                    plan_name=str(plan_name).strip(),
                    amount=clean_amount,
                    due_date=due_utc or datetime.now(timezone.utc),
                    payment_status="pendiente"
                )
                db.add(mem)
                created_count += 1
                details.append(f"Socio creado: {member_name} (${clean_amount})")

        # -----------------------------------------------------------------
        # C. VERTICAL: TALLERES & ÓPTICAS (Ready for Pickup & Balances)
        # -----------------------------------------------------------------
        elif business_type in ["taller", "optica"]:
            customer_name = clean_r.get("cliente") or clean_r.get("nombre")
            phone_raw = clean_r.get("telefono") or clean_r.get("celular") or clean_r.get("whatsapp")
            item_raw = clean_r.get("vehiculo_orden") or clean_r.get("trabajo_armazon") or clean_r.get("orden") or clean_r.get("trabajo")
            status_raw = str(clean_r.get("estado") or "en_proceso").lower().strip()
            balance_raw = clean_r.get("monto_saldo") or clean_r.get("saldo") or clean_r.get("precio") or 0.0

            if not customer_name or not phone_raw:
                continue

            clean_phone = "".join(filter(str.isdigit, str(phone_raw)))
            if not clean_phone.startswith("54") and len(clean_phone) == 10:
                clean_phone = f"549{clean_phone}"

            try:
                clean_balance = float(str(balance_raw).replace("$", "").replace(".", "").replace(",", ".").strip())
            except Exception:
                clean_balance = 0.0

            existing_cust = db.query(InactiveCustomer).filter(
                InactiveCustomer.tenant_id == tenant.id,
                InactiveCustomer.customer_phone == clean_phone
            ).first()

            if existing_cust:
                existing_cust.customer_name = str(customer_name).strip()
                existing_cust.service_or_product = str(item_raw or existing_cust.service_or_product)
                existing_cust.status = status_raw
                updated_count += 1
                details.append(f"Orden actualizada: {customer_name} ({status_raw})")
            else:
                cust = InactiveCustomer(
                    tenant_id=tenant.id,
                    customer_name=str(customer_name).strip(),
                    customer_phone=clean_phone,
                    service_or_product=str(item_raw or "Trabajo en Taller/Óptica"),
                    status=status_raw,
                    campaign_name="despacho_ordenes"
                )
                db.add(cust)
                created_count += 1
                details.append(f"Orden registrada: {customer_name} ({status_raw})")

            # Autonomous Trigger: If status changed to "listo" or "listo_para_retirar", notify customer
            if status_raw in ["listo", "listo_para_retirar", "terminado"]:
                saldo_msg = f"\n💵 *Saldo a abonar:* ${clean_balance:,.0f}" if clean_balance > 0 else ""
                pickup_msg = (
                    f"¡Hola {customer_name}! Te avisamos de *{tenant.name}* que tu orden/trabajo ya se encuentra listo para retirar 🙌\n\n"
                    f"🔧 *Detalle:* {item_raw or 'Trabajo terminado'}{saldo_msg}\n\n"
                    f"¡Podés pasar en nuestros horarios habituales!"
                )
                try:
                    await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=pickup_msg)
                    logger.info(f"📦 Aviso 'Listo para retirar' enviado a {clean_phone} para {tenant.name}")
                except Exception as notify_err:
                    logger.error(f"Error notifying ready order to {clean_phone}: {notify_err}")

        # -----------------------------------------------------------------
        # D. VERTICAL: VETERINARIAS (Vaccines & Preventive Care)
        # -----------------------------------------------------------------
        elif business_type in ["veterinaria"]:
            owner_name = clean_r.get("dueno") or clean_r.get("cliente") or clean_r.get("nombre")
            pet_name = clean_r.get("mascota") or "Mascota"
            phone_raw = clean_r.get("telefono") or clean_r.get("celular")
            service_raw = clean_r.get("servicio_vacuna") or clean_r.get("vacuna") or "Control Preventivo"
            due_raw = clean_r.get("proxima_fecha") or clean_r.get("fecha")

            if not owner_name or not phone_raw:
                continue

            clean_phone = "".join(filter(str.isdigit, str(phone_raw)))
            if not clean_phone.startswith("54") and len(clean_phone) == 10:
                clean_phone = f"549{clean_phone}"

            due_utc = parse_argentine_datetime(str(due_raw)) if due_raw else None

            existing_vet = db.query(InactiveCustomer).filter(
                InactiveCustomer.tenant_id == tenant.id,
                InactiveCustomer.customer_phone == clean_phone
            ).first()

            desc = f"Mascota: {pet_name} - {service_raw}"
            if existing_vet:
                existing_vet.customer_name = str(owner_name).strip()
                existing_vet.service_or_product = desc
                updated_count += 1
                details.append(f"Paciente vet actualizado: {pet_name} ({owner_name})")
            else:
                cust = InactiveCustomer(
                    tenant_id=tenant.id,
                    customer_name=str(owner_name).strip(),
                    customer_phone=clean_phone,
                    service_or_product=desc,
                    status="activo",
                    campaign_name="vacunacion_preventiva"
                )
                db.add(cust)
                created_count += 1
                details.append(f"Paciente vet registrado: {pet_name} ({owner_name})")

        # -----------------------------------------------------------------
        # E. VERTICAL: COMERCIO & MAYORISTAS (Products & Prices)
        # -----------------------------------------------------------------
        elif business_type in ["comercio", "mayorista", "distribuidora"]:
            product_name = clean_r.get("producto") or clean_r.get("item") or clean_r.get("nombre")
            price_raw = clean_r.get("precio") or clean_r.get("price") or 0.0
            stock_raw = clean_r.get("stock") or 0

            if not product_name:
                continue

            try:
                clean_price = float(str(price_raw).replace("$", "").replace(".", "").replace(",", ".").strip())
            except Exception:
                clean_price = 0.0

            owner_phone = tenant.owner_phone or "5493434536447"
            prod = db.query(MerchantProduct).filter(
                MerchantProduct.merchant_phone == owner_phone,
                MerchantProduct.name == str(product_name).strip()
            ).first()

            if prod:
                prod.price = clean_price
                updated_count += 1
                details.append(f"Producto actualizado: {product_name} (${clean_price})")
            else:
                prod = MerchantProduct(
                    merchant_phone=owner_phone,
                    name=str(product_name).strip(),
                    price=clean_price,
                    supplier="Stock Propio"
                )
                db.add(prod)
                created_count += 1
                details.append(f"Producto creado: {product_name} (${clean_price})")

    db.commit()

    logger.info(f"🔄 [Universal Sync] Sincronización completada para '{tenant.name}' ({tenant.slug}): {created_count} creados, {updated_count} actualizados.")

    return {
        "status": "success",
        "tenant_slug": tenant.slug,
        "tenant_name": tenant.name,
        "business_type": business_type,
        "source": source,
        "records_received": len(rows),
        "created_count": created_count,
        "updated_count": updated_count,
        "details": details[:10]  # First 10 samples
    }


@router.post("/{tenant_slug}/google-sheets")
async def sync_google_sheets_webhook(
    tenant_slug: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Dedicated endpoint optimized for Google Apps Script triggers.
    Accepts JSON body or raw text.
    """
    try:
        raw_body = await request.body()
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {e}")

    # Forward to main sync handler
    return await sync_tenant_data(tenant_slug=tenant_slug, payload=payload, db=db)
