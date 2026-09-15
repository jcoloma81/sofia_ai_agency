import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import excel_bridge
from app.services import whatsapp

logger = logging.getLogger(__name__)

router = APIRouter()

class EnqueueCommandRequest(BaseModel):
    merchant_phone: str
    action: str  # append_row, update_product, batch_update
    payload: Dict[str, Any]
    target_file: Optional[str] = None
    sheet_name: Optional[str] = None

class AcknowledgeRequest(BaseModel):
    command_id: str
    status: str = "completed"  # completed, failed
    result_message: Optional[str] = None
    notify_merchant: bool = False

@router.get("/commands")
def list_pending_commands(
    merchant_phone: str = Query(..., description="E.164 phone or identifier of the merchant"),
    db: Session = Depends(get_db)
):
    """
    Called by Sofía Bridge (running on merchant's PC) to fetch pending commands.
    """
    clean_p = "".join(filter(str.isdigit, merchant_phone))
    commands = excel_bridge.get_pending_commands(db, clean_p)
    return {
        "status": "success",
        "count": len(commands),
        "commands": commands
    }

@router.post("/ack")
async def acknowledge_bridge_command(
    req: AcknowledgeRequest,
    db: Session = Depends(get_db)
):
    """
    Called by Sofía Bridge when an Excel operation has been executed.
    Optionally sends a WhatsApp notification to the merchant with the confirmation.
    """
    cmd = excel_bridge.acknowledge_command(
        db=db,
        command_id=req.command_id,
        status=req.status,
        result_message=req.result_message
    )
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")

    if req.notify_merchant and cmd.merchant_phone and req.status == "completed":
        msg = f"📊 *Sofía Bridge Excel:* {req.result_message or 'Tu planilla se actualizó con éxito.'}"
        try:
            await whatsapp.send_whatsapp_message(cmd.merchant_phone, msg)
        except Exception as e:
            logger.warning(f"Could not send WhatsApp ACK notification: {e}")

    return {
        "status": "success",
        "command_id": cmd.command_id,
        "new_status": cmd.status,
        "result_message": cmd.result_message
    }

@router.post("/enqueue")
def enqueue_command(
    req: EnqueueCommandRequest,
    db: Session = Depends(get_db)
):
    """
    Manually enqueues a command for testing or integration.
    """
    clean_p = "".join(filter(str.isdigit, req.merchant_phone))
    cmd = excel_bridge.enqueue_bridge_command(
        db=db,
        merchant_phone=clean_p,
        action=req.action,
        payload=req.payload,
        target_file=req.target_file,
        sheet_name=req.sheet_name
    )
    return {
        "status": "success",
        "command_id": cmd.command_id,
        "action": cmd.action,
        "created_at": cmd.created_at.isoformat()
    }

@router.get("/price_query")
def pocket_price_query(
    merchant_phone: str = Query(...),
    query: str = Query(...),
    margin: float = Query(0.40),
    db: Session = Depends(get_db)
):
    """
    Pillar 2: Instant price consultation for mobile merchants.
    """
    clean_p = "".join(filter(str.isdigit, merchant_phone))
    prod = excel_bridge.lookup_merchant_product(db, clean_p, query, default_margin=margin)
    if not prod:
        return {
            "status": "not_found",
            "message": f"No se encontró '{query}' en tu lista de precios."
        }
    return {
        "status": "found",
        "product": prod,
        "formatted_text": excel_bridge.format_pocket_price_response(prod)
    }

@router.get("/download")
def download_bridge_package(
    merchant_phone: Optional[str] = Query(None, description="Optional merchant phone to pre-fill config.json")
):
    """
    Downloads a complete, self-contained ZIP installer with the Sofía Bridge
    scripts, launcher batch file, and pre-configured settings.
    """
    import io
    import os
    import json
    import zipfile
    from fastapi.responses import StreamingResponse

    zip_buffer = io.BytesIO()
    tools_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "tools")

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        bridge_py = os.path.join(tools_dir, "sofia_bridge.py")
        if os.path.exists(bridge_py):
            zf.write(bridge_py, arcname="sofia_bridge.py")

        bat_file = os.path.join(tools_dir, "iniciar_bridge.bat")
        if os.path.exists(bat_file):
            zf.write(bat_file, arcname="iniciar_bridge.bat")

        readme_file = os.path.join(tools_dir, "LEEME_INSTALACION.txt")
        if os.path.exists(readme_file):
            zf.write(readme_file, arcname="LEEME_INSTALACION.txt")

        clean_p = "".join(filter(str.isdigit, merchant_phone or "5493434991122"))
        config_data = {
            "merchant_phone": clean_p,
            "server_url": "https://sofia-ai-agency.onrender.com",
            "excel_path": "ferreteria_demo.xlsx",
            "poll_interval": 2
        }
        zf.writestr("config.json", json.dumps(config_data, indent=2))

    zip_buffer.seek(0)
    filename = f"Sofia_Bridge_{clean_p if merchant_phone else 'Setup'}.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
