import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from difflib import SequenceMatcher

from app.models.prospect import BridgeCommand, MerchantProduct
from app.services.catalog import clean_price

logger = logging.getLogger(__name__)

def utc_now():
    return datetime.now(timezone.utc)

def enqueue_bridge_command(
    db: Session,
    merchant_phone: str,
    action: str,
    payload: Dict[str, Any],
    target_file: Optional[str] = None,
    sheet_name: Optional[str] = None
) -> BridgeCommand:
    """
    Enqueues a new command for the merchant's desktop Excel bridge.
    action: 'append_row', 'update_product', 'batch_update'
    """
    cmd_id = str(uuid.uuid4())
    cmd = BridgeCommand(
        command_id=cmd_id,
        merchant_phone=merchant_phone,
        action=action,
        target_file=target_file,
        sheet_name=sheet_name,
        payload=json.dumps(payload, ensure_ascii=False),
        status="pending",
        created_at=utc_now()
    )
    db.add(cmd)
    db.commit()
    db.refresh(cmd)
    logger.info(f"⚡ [Bridge] Enqueued command {cmd_id} for merchant {merchant_phone} (action={action})")
    return cmd

def get_pending_commands(db: Session, merchant_phone: str) -> List[Dict[str, Any]]:
    """
    Retrieves all pending commands for a specific merchant.
    """
    records = db.query(BridgeCommand).filter(
        BridgeCommand.merchant_phone == merchant_phone,
        BridgeCommand.status == "pending"
    ).order_by(BridgeCommand.created_at.asc()).all()

    result = []
    for r in records:
        try:
            parsed_payload = json.loads(r.payload) if r.payload else {}
        except Exception:
            parsed_payload = {}
        result.append({
            "command_id": r.command_id,
            "merchant_phone": r.merchant_phone,
            "action": r.action,
            "target_file": r.target_file,
            "sheet_name": r.sheet_name,
            "payload": parsed_payload,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None
        })
    return result

def acknowledge_command(
    db: Session,
    command_id: str,
    status: str = "completed",
    result_message: Optional[str] = None
) -> Optional[BridgeCommand]:
    """
    Acknowledges execution of a bridge command from the desktop client.
    """
    cmd = db.query(BridgeCommand).filter(
        BridgeCommand.command_id == command_id
    ).first()
    if not cmd:
        logger.warning(f"⚠️ [Bridge] Command {command_id} not found for ACK")
        return None

    cmd.status = status
    cmd.result_message = result_message
    cmd.completed_at = utc_now()
    db.commit()
    db.refresh(cmd)
    logger.info(f"✅ [Bridge] Command {command_id} marked as {status}: {result_message}")
    return cmd

# ==============================================================================
# Pillar 2: Mobile Merchant Pocket Assistant (Price & Stock Queries)
# ==============================================================================

def lookup_merchant_product(
    db: Session,
    merchant_phone: str,
    query: str,
    default_margin: float = 0.40
) -> Optional[Dict[str, Any]]:
    """
    Searches for a product in merchant's registered price lists/catalog.
    Calculates cost, sale price with profit margin, stock, and returns formatted info.
    """
    clean_q = query.strip().lower()
    if not clean_q:
        return None

    # Find candidate products for this merchant
    prods = db.query(MerchantProduct).filter(
        MerchantProduct.merchant_phone == merchant_phone
    ).all()

    if not prods:
        return None

    best_prod = None
    best_score = 0.0

    for p in prods:
        p_name = (p.name or "").lower()
        score = SequenceMatcher(None, clean_q, p_name).ratio()
        # Bonus if all query words appear in product name
        q_words = clean_q.split()
        if all(w in p_name for w in q_words):
            score += 0.4

        if score > best_score:
            best_score = score
            best_prod = p

    if best_prod and best_score >= 0.5:
        cost = best_prod.cost_price or best_prod.price
        sale_price = best_prod.price
        if best_prod.cost_price and (best_prod.price == 0.0 or best_prod.price == best_prod.cost_price):
            sale_price = round(cost * (1.0 + default_margin), 2)

        return {
            "name": best_prod.name,
            "cost_price": cost,
            "sale_price": sale_price,
            "margin_percent": int(default_margin * 100),
            "in_stock": best_prod.in_stock,
            "supplier": best_prod.supplier_name,
            "category": best_prod.category,
            "presentation": best_prod.presentation,
            "code": best_prod.code,
            "updated_at": best_prod.updated_at
        }

    return None

def format_pocket_price_response(prod_info: Dict[str, Any]) -> str:
    """Formats an instant pocket price response for WhatsApp / audio."""
    def fmt_curr(amount: float) -> str:
        if amount.is_integer():
            return f"${int(amount):,}".replace(",", ".")
        return f"${amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    name = prod_info["name"]
    sale_str = fmt_curr(prod_info["sale_price"])
    cost_str = fmt_curr(prod_info["cost_price"])
    margin = prod_info["margin_percent"]
    stock_str = "En stock ✅" if prod_info.get("in_stock", True) else "Sin stock ❌"
    supplier = prod_info.get("supplier", "Proveedor")

    return (
        f"🔍 *{name}*\n\n"
        f"🏷️ *Precio Venta:* {sale_str} (con {margin}% margen)\n"
        f"📦 *Costo:* {cost_str} ({supplier})\n"
        f"📊 *Estado:* {stock_str}"
    )

def apply_supplier_price_update(
    db: Session,
    merchant_phone: str,
    supplier_name: str,
    items: List[Dict[str, Any]],
    default_margin: float = 0.40,
    sync_to_bridge: bool = True
) -> Dict[str, Any]:
    """
    Updates or inserts products from supplier price list in DB.
    Optionally enqueues a batch_update command to merchant's desktop Excel bridge.
    """
    updated_count = 0
    created_count = 0
    bridge_items = []

    for item in items:
        raw_name = str(item.get("name", "")).strip()
        if not raw_name:
            continue
        new_cost = clean_price(item.get("price") or item.get("cost_price", 0))
        new_sale = round(new_cost * (1.0 + default_margin), 2)
        code = item.get("code")

        existing = db.query(MerchantProduct).filter(
            MerchantProduct.merchant_phone == merchant_phone,
            MerchantProduct.supplier_name == supplier_name,
            MerchantProduct.name == raw_name
        ).first()

        if existing:
            existing.cost_price = new_cost
            existing.price = new_sale
            if code:
                existing.code = str(code)
            existing.updated_at = utc_now()
            updated_count += 1
        else:
            new_p = MerchantProduct(
                merchant_phone=merchant_phone,
                supplier_name=supplier_name,
                name=raw_name,
                cost_price=new_cost,
                price=new_sale,
                code=str(code) if code else None,
                presentation=item.get("presentation", "Unidad"),
                category=item.get("category", "General"),
                in_stock=True,
                created_at=utc_now()
            )
            db.add(new_p)
            created_count += 1

        bridge_items.append({
            "name": raw_name,
            "cost_price": new_cost,
            "sale_price": new_sale,
            "code": code
        })

    db.commit()

    bridge_cmd_id = None
    if sync_to_bridge and bridge_items:
        cmd = enqueue_bridge_command(
            db=db,
            merchant_phone=merchant_phone,
            action="batch_update",
            payload={
                "supplier_name": supplier_name,
                "default_margin": default_margin,
                "items": bridge_items
            }
        )
        bridge_cmd_id = cmd.command_id

    return {
        "updated_count": updated_count,
        "created_count": created_count,
        "total_processed": len(bridge_items),
        "bridge_command_id": bridge_cmd_id
    }


def parse_pocket_price_query(text: str) -> Optional[str]:
    """
    Detects if merchant is asking for their own product's selling price or cost in WhatsApp:
    e.g. 'a cuánto tengo la cal', 'cuánto sale el caño de 110', 'precio de los tornillos',
    'a cuánto cobro el metro de cable'
    """
    import re
    clean = text.strip()
    clean = re.sub(r'^[¿?¡!]+|[¿?¡!]+$', '', clean).strip()
    lower = clean.lower()

    # Exclude general agency inquiries or boss commands
    if any(k in lower for k in [
        "lista de precio", "lista de precios", "mandale el pedido", "anota para", "anotá para",
        "borrar al proveedor", "eliminar proveedor", "alta cliente", "resumen de ventas"
    ]):
        return None

    patterns = [
        r'(?:a cuánto|a cuanto|cuanto|cuánto)\s+(?:tengo|está|esta|cobro|vendo|sale|vale)\s+(?:el|la|los|las|un|una|el rollo de|la bolsa de|la caja de)?\s*(.+)',
        r'(?:decime\s+el\s+)?precio\s+(?:de|del|de la|de los|de las)\s+(.+)',
        r'(?:cuál\s+es\s+el\s+|cual\s+es\s+el\s+)?costo\s+(?:de|del|de la|de los|de las)\s+(.+)',
        r'(?:cuánto\s+me\s+queda\s+de|stock\s+de|hay\s+stock\s+de)\s+(.+)'
    ]
    for pat in patterns:
        m = re.search(pat, clean, re.IGNORECASE)
        if m:
            cand = m.group(1).strip()
            cand = re.sub(r'[\?¿\.\,\!]+$', '', cand).strip()
            if len(cand) >= 3 and not cand.startswith("tu ") and not cand.startswith("el servicio"):
                return cand
    return None


async def parse_bridge_excel_intent(text: str) -> Dict[str, Any]:
    """
    Detects if the merchant wants to manipulate their PC Excel spreadsheet:
    - 'anotá en el excel venta de 2 curvas 110 y 1 pegamento por $11.600'
    - 'cambiá en el excel el precio de la cal a $4.800 y 15 de stock'
    - 'poné en el excel que de cemento me quedan 30'
    """
    import re
    clean = text.strip()
    lower = clean.lower()

    if not any(k in lower for k in ["excel", "planilla", "pc", "compu"]):
        return {"is_bridge": False}

    # 1. Try Gemini Flash Lite for robust entity extraction
    from app.config.settings import settings
    import httpx
    gemini_key = getattr(settings, "GEMINI_API_KEY", None)
    if gemini_key:
        prompt = (
            "El comerciante envió una orden para modificar su planilla de Microsoft Excel abierta en su PC:\n"
            f"Mensaje: \"{clean}\"\n\n"
            "Analizá la intención y respondé ÚNICAMENTE un JSON con este esquema:\n"
            "{\n"
            '  "is_bridge": true,\n'
            '  "action": "append_row" | "update_product" | "batch_update",\n'
            '  "sheet_name": "Ventas" o "Precios" o null,\n'
            '  "search_term": "nombre del producto a buscar si es update_product" o null,\n'
            '  "updates": {"precio": float o null, "stock": int o null, "costo": float o null} o null,\n'
            '  "values": ["valor1", "valor2", ...] si es append_row o null,\n'
            '  "summary": "Breve confirmación humana en español (ej: Cambié la Cal Loma Negra a $4.800 en tu Excel)"\n'
            "}"
        )
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={gemini_key}"
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.post(
                    url,
                    json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"response_mime_type": "application/json"}}
                )
                if res.status_code == 200:
                    data = res.json()
                    cands = data.get("candidates", [])
                    if cands and "content" in cands[0]:
                        parts = cands[0]["content"].get("parts", [])
                        if parts:
                            parsed = json.loads(parts[0].get("text", "{}"))
                            if parsed.get("is_bridge"):
                                return parsed
        except Exception as e:
            logger.warning(f"Error in Gemini bridge intent parse: {e}")

    # Fallback regex parsing if offline or Gemini fails
    update_m = re.search(r'(?:cambi[aá]|modific[aá]|actualiz[aá]|pon[eé])\s+(?:en\s+(?:el\s+)?(?:excel|planilla)\s+)?(?:el\s+precio\s+de\s+|la\s+)?(.+?)\s+a\s+\$?([\d\.\,]+)', clean, re.IGNORECASE)
    if update_m:
        prod_cand = update_m.group(1).strip()
        new_price = clean_price(update_m.group(2))
        return {
            "is_bridge": True,
            "action": "update_product",
            "sheet_name": "Precios",
            "search_term": prod_cand,
            "updates": {"precio": new_price},
            "summary": f"Cambié '{prod_cand}' a ${int(new_price):,} en tu Excel."
        }

    append_m = re.search(r'(?:anot[aá]|agreg[aá]|pas[aá])\s+(?:en\s+(?:el\s+)?(?:excel|planilla)\s+)?(?:venta|renglon|fila)?\s*(.+)', clean, re.IGNORECASE)
    if append_m:
        detail = append_m.group(1).strip()
        return {
            "is_bridge": True,
            "action": "append_row",
            "sheet_name": "Ventas",
            "values": [datetime.now().strftime("%d/%m"), datetime.now().strftime("%H:%M"), detail, 0],
            "summary": f"Anoté la venta en tu Excel: {detail}"
        }

    return {"is_bridge": False}
