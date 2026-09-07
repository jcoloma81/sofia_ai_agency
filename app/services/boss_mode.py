import re
import json
import logging
from typing import Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.prospect import Prospect
from app.services.catalog import catalog_service

logger = logging.getLogger(__name__)

def is_boss_number(phone: str) -> bool:
    """Verifies if the sender phone matches the configured owner/boss alert line."""
    clean_sender = "".join(filter(str.isdigit, str(phone)))
    clean_boss = "".join(filter(str.isdigit, str(settings.WHATSAPP_ALERT_PHONE or "")))
    if not clean_sender or not clean_boss:
        return False
    return clean_sender == clean_boss or clean_boss.endswith(clean_sender) or clean_sender.endswith(clean_boss)

async def process_boss_message(
    db: Session,
    sender_phone: str,
    text: str,
    doc_bytes: Optional[bytes] = None,
    doc_name: Optional[str] = None
) -> Tuple[bool, str, str]:
    """
    Executes executive commands sent by the business owner directly from WhatsApp:
    1. 'resumen' / 'ventas' / 'pedidos' -> metrics & status
    2. 'pausar <tel>' / 'silenciar <tel>' -> human takeover
    3. 'activar <tel>' / 'reactivar <tel>' -> restore Sofia
    4. 'catalogo' / 'actualizar catalogo' -> check or refresh catalog
    5. Uploading an Excel (.xlsx) or CSV file -> loads into catalog
    """
    clean_text = text.strip()
    lower_text = clean_text.lower()

    # 1. Excel / CSV File upload
    if doc_bytes and doc_name:
        fname = doc_name.lower()
        if fname.endswith(".xlsx") or fname.endswith(".xls"):
            count = catalog_service.load_from_excel_bytes(doc_bytes, filename=doc_name)
            return True, f"✅ *¡Lista de precios cargada con éxito!*\n\nSe procesaron *{count} productos* desde el archivo `{doc_name}`. Sofía ya está lista para cotizar y tomar pedidos con estos nuevos precios.", "catalog_updated"
        elif fname.endswith(".csv"):
            try:
                csv_str = doc_bytes.decode("utf-8")
            except UnicodeDecodeError:
                csv_str = doc_bytes.decode("latin-1", errors="ignore")
            count = catalog_service.load_from_csv(csv_str, source_name=doc_name)
            return True, f"✅ *¡Lista de precios cargada con éxito!*\n\nSe procesaron *{count} productos* desde el archivo `{doc_name}`.", "catalog_updated"

    # 2. Status & Metrics Summary
    if any(k in lower_text for k in ["resumen", "estado", "ventas", "pedidos", "como venimos", "cómo venimos", "metricas", "métricas"]):
        total_prospects = db.query(Prospect).count()
        in_conversation = db.query(Prospect).filter(Prospect.status == "in_conversation").count()
        meetings = db.query(Prospect).filter(Prospect.status == "meeting_scheduled").count()
        human_takeover = db.query(Prospect).filter(Prospect.status == "human_takeover").count()
        orders = db.query(Prospect).filter(Prospect.status == "order_confirmed").count()

        cat_info = f"{len(catalog_service.products)} productos activos ({catalog_service.source_info})"

        reply = (
            f"📊 *REPORTE EJECUTIVO EN TIEMPO REAL* 📊\n\n"
            f"🤖 *Estado de Sofía:* 100% Operativa\n"
            f"📦 *Catálogo:* {cat_info}\n\n"
            f"📈 *Métricas Clave:*\n"
            f"• 👥 Total contactos registrados: *{total_prospects}*\n"
            f"• 💬 En conversación activa: *{in_conversation}*\n"
            f"• 🎯 Citas agendadas: *{meetings}*\n"
            f"• 📦 Pedidos confirmados: *{orders}*\n"
            f"• 👤 En atención manual: *{human_takeover}*\n\n"
            f"💡 *Comandos disponibles:*\n"
            f"- `pausar <número>` para atender vos a un cliente\n"
            f"- `activar <número>` para devolverle el chat a Sofía\n"
            f"- `catalogo` para ver o actualizar lista"
        )
        return True, reply, "boss_metrics"

    # 3. Human Takeover (Pause Sofia for a number)
    if any(lower_text.startswith(w) for w in ["pausar", "silenciar", "frenar", "parar"]):
        num_matches = re.findall(r'\d+', lower_text)
        if num_matches:
            target_number = num_matches[-1]
            target_lead = db.query(Prospect).filter(Prospect.phone.like(f"%{target_number}%")).first()
            if target_lead:
                target_lead.status = "human_takeover"
                db.commit()
                return True, f"👤 *Listo Javier:* Sofía fue silenciada para *{target_lead.name}* (+{target_lead.phone}). Ahora podés chatear vos directamente sin que la IA intervenga.", "human_takeover_set"
            return True, f"⚠️ No encontré ningún contacto con el número `{target_number}`.", "lead_not_found"
        return True, "💡 Para pausar a Sofía en un chat, escribí: `pausar <número>` (ej: `pausar 400964`).", "invalid_syntax"

    # 4. Reactivate Sofia for a number
    if any(lower_text.startswith(w) for w in ["activar", "reactivar"]):
        num_matches = re.findall(r'\d+', lower_text)
        if num_matches:
            target_number = num_matches[-1]
            target_lead = db.query(Prospect).filter(Prospect.phone.like(f"%{target_number}%")).first()
            if target_lead:
                target_lead.status = "in_conversation"
                db.commit()
                return True, f"✅ *Listo Javier:* Reactivé la atención de Sofía para *{target_lead.name}* (+{target_lead.phone}). Sofía retomará la conversación normalmente.", "lead_reactivated"
            return True, f"⚠️ No encontré ningún contacto con el número `{target_number}`.", "lead_not_found"
        return True, "💡 Para reactivar a Sofía en un chat, escribí: `activar <número>` (ej: `activar 400964`).", "invalid_syntax"

    # 5. Catalog Check / Refresh
    if any(k in lower_text for k in ["catalogo", "catálogo", "lista de precios", "productos"]):
        summary = catalog_service.get_summary_prompt(max_items=15)
        reply = (
            f"📦 *ESTADO DEL CATÁLOGO ACTUAL*\n\n"
            f"{summary}\n\n"
            f"💡 *Para actualizar precios:* Podés mandarme un archivo `.xlsx` o `.csv` adjunto por este chat o editar tu Google Sheet."
        )
        return True, reply, "catalog_view"

    # 6. Default helpful response to boss
    return True, (
        "👋 *Hola Javier!*\n\n"
        "Estoy activa y monitoreando todos los canales. Podés pedirme:\n"
        "• `resumen` o `pedidos`: ver métricas y ventas del día.\n"
        "• `pausar <número>`: silenciar a Sofía en un chat específico.\n"
        "• `activar <número>`: volver a activar la IA en ese chat.\n"
        "• `catalogo`: ver lista de productos cargados.\n"
        "• O enviarme un archivo Excel con la nueva lista de precios."
    ), "boss_help"
