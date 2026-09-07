import io
import re
import csv
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timezone
import httpx
import openpyxl

logger = logging.getLogger(__name__)

@dataclass
class ProductItem:
    name: str
    price: float
    presentation: str = "Unidad"
    category: str = "General"
    in_stock: bool = True
    code: Optional[str] = None

    def formatted_price(self) -> str:
        """Returns Argentine-formatted currency string e.g. $14.400"""
        if self.price.is_integer():
            return f"${int(self.price):,}".replace(",", ".")
        return f"${self.price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def clean_price(val: Any) -> float:
    """
    Parses various currency formats into a float:
    e.g. '$ 14.400,50', '14,400', '14400', '14.400', '$2.500,00'
    """
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)

    s = str(val).strip()
    s = re.sub(r'[^\d.,]', '', s)
    if not s:
        return 0.0

    if "." in s and "," in s:
        # Check which separator comes last
        if s.rfind(",") > s.rfind("."):
            # Argentine/Spanish: 14.400,50
            s = s.replace(".", "").replace(",", ".")
        else:
            # English/US: 14,400.50
            s = s.replace(",", "")
    elif "," in s:
        # If comma is decimal (e.g. 14400,50 or 25,00)
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = f"{parts[0]}.{parts[1]}"
        else:
            s = s.replace(",", "")
    elif "." in s:
        # If dot is thousands separator (e.g. 14.400)
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            s = s.replace(".", "")

    try:
        return float(s)
    except Exception:
        return 0.0


def clean_stock(val: Any) -> bool:
    """Detects if product is in stock from common Spanish terms."""
    if val is None:
        return True
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ["no", "0", "false", "sin stock", "agotado", "no disponible", "n"]:
        return False
    return True


def identify_columns(headers: List[str]) -> Dict[str, Optional[int]]:
    """Intelligently detects column indices based on flexible synonyms."""
    mapping: Dict[str, Optional[int]] = {
        "name": None,
        "price": None,
        "presentation": None,
        "stock": None,
        "category": None,
        "code": None
    }

    for idx, raw_h in enumerate(headers):
        h = str(raw_h or "").strip().lower()
        if not h:
            continue

        if mapping["name"] is None and any(k in h for k in ["producto", "articulo", "artículo", "descripcion", "descripción", "detalle", "nombre", "item"]):
            mapping["name"] = idx
        elif mapping["price"] is None and any(k in h for k in ["precio", "valor", "importe", "costo", "p.unit", "p.vta"]):
            mapping["price"] = idx
        elif mapping["presentation"] is None and any(k in h for k in ["presentacion", "presentación", "bulto", "envase", "medida", "unidad", "pack"]):
            mapping["presentation"] = idx
        elif mapping["stock"] is None and any(k in h for k in ["stock", "disponible", "hay", "estado"]):
            mapping["stock"] = idx
        elif mapping["category"] is None and any(k in h for k in ["categoria", "categoría", "rubro", "familia"]):
            mapping["category"] = idx
        elif mapping["code"] is None and any(k in h for k in ["codigo", "código", "cod", "sku", "id"]):
            mapping["code"] = idx

    if mapping["name"] is None and len(headers) > 0:
        mapping["name"] = 0
    if mapping["price"] is None and len(headers) > 1:
        mapping["price"] = 1

    return mapping


class CatalogService:
    def __init__(self):
        self.products: List[ProductItem] = []
        self.last_updated: Optional[datetime] = None
        self.source_info: str = "Empty"

    def load_from_csv(self, csv_content: str, source_name: str = "CSV") -> int:
        """Parses CSV text into product catalog."""
        if not csv_content or not csv_content.strip():
            return 0

        first_line = csv_content.strip().split("\n")[0]
        delimiter = ";" if ";" in first_line else ","

        reader = csv.reader(io.StringIO(csv_content.strip()), delimiter=delimiter)
        rows = list(reader)
        if not rows:
            return 0

        headers = [h.strip() for h in rows[0]]
        col_map = identify_columns(headers)

        items: List[ProductItem] = []
        for row in rows[1:]:
            if not row or not any(row):
                continue
            name_idx = col_map["name"]
            price_idx = col_map["price"]
            if name_idx is None or name_idx >= len(row):
                continue

            raw_name = str(row[name_idx]).strip()
            if not raw_name:
                continue

            raw_price = row[price_idx] if (price_idx is not None and price_idx < len(row)) else 0.0
            price = clean_price(raw_price)

            presentation = "Unidad"
            if col_map["presentation"] is not None and col_map["presentation"] < len(row):
                p_val = str(row[col_map["presentation"]]).strip()
                if p_val:
                    presentation = p_val

            category = "General"
            if col_map["category"] is not None and col_map["category"] < len(row):
                c_val = str(row[col_map["category"]]).strip()
                if c_val:
                    category = c_val

            in_stock = True
            if col_map["stock"] is not None and col_map["stock"] < len(row):
                in_stock = clean_stock(row[col_map["stock"]])

            code = None
            if col_map["code"] is not None and col_map["code"] < len(row):
                cd = str(row[col_map["code"]]).strip()
                if cd:
                    code = cd

            items.append(ProductItem(
                name=raw_name,
                price=price,
                presentation=presentation,
                category=category,
                in_stock=in_stock,
                code=code
            ))

        self.products = items
        self.last_updated = datetime.now(timezone.utc)
        self.source_info = f"{source_name} ({len(items)} productos)"
        logger.info(f"Loaded {len(items)} products from {source_name}")
        return len(items)

    def load_from_excel_bytes(self, content: bytes, filename: str = "Excel") -> int:
        """Parses Excel workbook bytes into product catalog."""
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            sheet = wb.active
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                return 0

            headers = [str(h or "").strip() for h in rows[0]]
            col_map = identify_columns(headers)

            items: List[ProductItem] = []
            for row in rows[1:]:
                if not row or not any(row):
                    continue
                name_idx = col_map["name"]
                price_idx = col_map["price"]
                if name_idx is None or name_idx >= len(row):
                    continue

                raw_name = str(row[name_idx] or "").strip()
                if not raw_name:
                    continue

                raw_price = row[price_idx] if (price_idx is not None and price_idx < len(row)) else 0.0
                price = clean_price(raw_price)

                presentation = "Unidad"
                if col_map["presentation"] is not None and col_map["presentation"] < len(row):
                    p_val = str(row[col_map["presentation"]] or "").strip()
                    if p_val:
                        presentation = p_val

                category = "General"
                if col_map["category"] is not None and col_map["category"] < len(row):
                    c_val = str(row[col_map["category"]] or "").strip()
                    if c_val:
                        category = c_val

                in_stock = True
                if col_map["stock"] is not None and col_map["stock"] < len(row):
                    in_stock = clean_stock(row[col_map["stock"]])

                code = None
                if col_map["code"] is not None and col_map["code"] < len(row):
                    cd = str(row[col_map["code"]] or "").strip()
                    if cd:
                        code = cd

                items.append(ProductItem(
                    name=raw_name,
                    price=price,
                    presentation=presentation,
                    category=category,
                    in_stock=in_stock,
                    code=code
                ))

            self.products = items
            self.last_updated = datetime.now(timezone.utc)
            self.source_info = f"{filename} ({len(items)} productos)"
            logger.info(f"Loaded {len(items)} products from Excel: {filename}")
            return len(items)
        except Exception as e:
            logger.error(f"Error reading Excel bytes: {e}")
            return 0

    @staticmethod
    def normalize_google_sheet_url(url: str) -> str:
        """Converts Google Sheet view / edit URL into direct CSV export URL."""
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
        if match:
            sheet_id = match.group(1)
            gid_match = re.search(r'[#&?]gid=([0-9]+)', url)
            gid = gid_match.group(1) if gid_match else "0"
            return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
        
        if "/pubhtml" in url:
            return url.replace("/pubhtml", "/pub?output=csv")
            
        return url

    async def load_from_google_sheets(self, url: str) -> int:
        """Downloads live Google Sheet as CSV and loads products."""
        csv_url = self.normalize_google_sheet_url(url)
        logger.info(f"Fetching Google Sheet CSV from: {csv_url}")
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                res = await client.get(csv_url)
                if res.status_code == 200 and res.text:
                    return self.load_from_csv(res.text, source_name="Google Sheets")
                else:
                    logger.error(f"Failed to fetch Google Sheet: status {res.status_code}")
                    return 0
        except Exception as e:
            logger.error(f"Error fetching Google Sheets: {e}")
            return 0

    def search_products(self, query: str, limit: int = 5) -> List[ProductItem]:
        """Performs case-insensitive keyword search in product names and categories."""
        if not query or not query.strip():
            return self.products[:limit]

        tokens = [t.strip().lower() for t in query.split() if len(t.strip()) > 1]
        matches = []
        for p in self.products:
            name_lower = p.name.lower()
            category_lower = p.category.lower()
            if all(t in name_lower or t in category_lower for t in tokens):
                matches.append(p)
            elif any(t in name_lower for t in tokens):
                matches.append(p)

        matches.sort(key=lambda p: (not p.in_stock, not (query.lower() in p.name.lower())))
        return matches[:limit]

    def find_product_exact_or_best(self, name_or_code: str) -> Optional[ProductItem]:
        """Finds closest product match by code or name."""
        if not name_or_code:
            return None
        clean_target = name_or_code.strip().lower()

        for p in self.products:
            if p.code and p.code.strip().lower() == clean_target:
                return p

        for p in self.products:
            if p.name.strip().lower() == clean_target:
                return p

        candidates = self.search_products(name_or_code, limit=1)
        if candidates:
            return candidates[0]

        return None

    def get_summary_prompt(self, max_items: int = 40) -> str:
        """Returns concise text for Gemini prompt injection."""
        if not self.products:
            return "Catálogo: No hay productos cargados actualmente."

        lines = [f"CATÁLOGO DE PRODUCTOS DISPONIBLES (Total: {len(self.products)}):"]
        for p in self.products[:max_items]:
            stock_str = "Disponible" if p.in_stock else "SIN STOCK"
            lines.append(f"- {p.name} [{p.presentation}]: {p.formatted_price()} ({stock_str})")
        
        if len(self.products) > max_items:
            lines.append(f"... y {len(self.products) - max_items} productos más.")

        return "\n".join(lines)

    def format_price_list(self) -> str:
        """Formats customer-facing WhatsApp price list message."""
        if not self.products:
            return "📋 *Lista de Precios:* Actualmente estamos actualizando la lista de productos."

        categories: Dict[str, List[ProductItem]] = {}
        for p in self.products:
            cat = p.category or "General"
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(p)

        blocks = ["📋 *LISTA DE PRECIOS ACTUALIZADA* 📋\n"]
        for cat, items in categories.items():
            blocks.append(f"*{cat.upper()}*")
            for p in items:
                status = "" if p.in_stock else " *(Sin stock)*"
                blocks.append(f"• {p.name} ({p.presentation}): *{p.formatted_price()}*{status}")
            blocks.append("")

        blocks.append("💡 *Para hacer un pedido, escribí o mandá un audio con los productos y cantidades que necesitás.*")
        return "\n".join(blocks)


catalog_service = CatalogService()

# Auto-initialize with sample catalog if available
import os
_default_csv = os.path.join(os.path.dirname(__file__), "..", "data", "sample_catalog.csv")
if os.path.exists(_default_csv):
    try:
        with open(_default_csv, "r", encoding="utf-8") as _f:
            catalog_service.load_from_csv(_f.read(), source_name="Catálogo Base")
    except Exception as _e:
        logger.warning(f"Could not load base catalog: {_e}")
