import io
import re
import csv
import logging
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone
import httpx
from difflib import SequenceMatcher
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

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
    e.g. '$ 14.400,50', '14,400', '14400', '14.400', '$2.500,00', '$ 58.000.-'
    """
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)

    s = str(val).strip()
    s = re.sub(r'[.-]+$', '', s)
    s = re.sub(r'[^\d.,]', '', s)
    s = s.strip(".,")
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
        # If dot is thousands separator (e.g. 14.400 or 1.250.000)
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            s = s.replace(".", "")
        elif len(parts) > 2:
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

        if mapping["name"] is None and any(k in h for k in [
            "producto", "articulo", "artículo", "descripcion", "descripción", 
            "detalle", "nombre", "item", "denominacion", "denominación"
        ]):
            mapping["name"] = idx
        elif mapping["price"] is None and any(k in h for k in [
            "precio", "valor", "importe", "costo", "p.unit", "p.vta", "p.lista", 
            "mayorista", "final", "total", "contado", "pvp", "pesos", "$"
        ]):
            mapping["price"] = idx
        elif mapping["presentation"] is None and any(k in h for k in [
            "presentacion", "presentación", "bulto", "envase", "medida", 
            "unidad", "pack", "formato", "caja", "fardo"
        ]):
            mapping["presentation"] = idx
        elif mapping["stock"] is None and any(k in h for k in [
            "stock", "disponible", "hay", "estado", "disp"
        ]):
            mapping["stock"] = idx
        elif mapping["category"] is None and any(k in h for k in [
            "categoria", "categoría", "rubro", "familia", "seccion", "sección", "grupo", "linea", "línea"
        ]):
            mapping["category"] = idx
        elif mapping["code"] is None and any(k in h for k in [
            "codigo", "código", "cod", "sku", "id", "ref", "referencia", "art"
        ]):
            mapping["code"] = idx

    if mapping["name"] is None and len(headers) > 0:
        mapping["name"] = 0
    if mapping["price"] is None and len(headers) > 1:
        mapping["price"] = 1

    return mapping


def find_header_and_mapping(rows: List[Any]) -> Tuple[int, Dict[str, Optional[int]]]:
    """
    Scans candidate rows (e.g. up to 25 rows) to automatically locate the real
    table header, bypassing company logos, titles, dates, instructions, and blank lines.
    """
    best_idx = 0
    best_score = -1
    best_mapping: Dict[str, Optional[int]] = {
        "name": None, "price": None, "presentation": None,
        "stock": None, "category": None, "code": None
    }

    max_rows = min(25, len(rows))
    for idx in range(max_rows):
        row = rows[idx]
        if not row or not any(row):
            continue
        headers = [str(cell or "").strip() for cell in row]
        m = identify_columns(headers)

        score = 0
        if m["name"] is not None and m["price"] is not None:
            score += 100
        elif m["name"] is not None or m["price"] is not None:
            score += 30

        for k in ["presentation", "stock", "category", "code"]:
            if m[k] is not None:
                score += 15

        if score > best_score:
            best_score = score
            best_idx = idx
            best_mapping = m
            if score >= 130:
                break

    # If no header was recognized by keywords, fallback to first non-empty row
    if best_score < 30:
        for idx in range(max_rows):
            if rows[idx] and any(rows[idx]):
                best_idx = idx
                best_mapping = identify_columns([str(c or "").strip() for c in rows[idx]])
                if best_mapping["name"] is None:
                    best_mapping["name"] = 0
                if best_mapping["price"] is None and len(rows[idx]) > 1:
                    best_mapping["price"] = 1
                break

    if best_mapping["name"] is None:
        best_mapping["name"] = 0
    if best_mapping["price"] is None and rows and len(rows[best_idx]) > 1:
        best_mapping["price"] = 1

    return best_idx, best_mapping


def extract_section_category(row: List[Any], name_idx: Optional[int]) -> Tuple[bool, Optional[str]]:
    """
    Detects if a row is an organizational section divider (e.g. '--- LÁCTEOS ---', 'RUBRO: BEBIDAS')
    or a repeated table header from printed page breaks.
    Returns (is_divider_or_header, category_name_if_any).
    """
    if not row:
        return False, None

    str_cells = [str(c or "").strip() for c in row if c is not None and str(c).strip()]
    if not str_cells:
        return False, None

    joined_lower = " ".join(str_cells).lower()
    # Repeated table header across pages
    if any(k in joined_lower for k in ["precio", "p.unit", "p.vta", "mayorista", "precio venta"]) and \
       any(k in joined_lower for k in ["producto", "articulo", "artículo", "descripcion", "descripción", "detalle", "cod"]):
        return True, None

    candidate_texts = []
    if name_idx is not None and name_idx < len(row) and row[name_idx]:
        candidate_texts.append(str(row[name_idx]).strip())
    if len(row) > 0 and row[0] and str(row[0]).strip() not in candidate_texts:
        candidate_texts.append(str(row[0]).strip())

    for s in candidate_texts:
        s_lower = s.lower()
        if s.startswith(("---", "***", "===", "###")):
            cat = s.strip("-*= #").strip()
            return True, cat if cat else None

        if s_lower.startswith(("rubro:", "rubro ", "categoria:", "categoría:", "familia:", "seccion:", "sección:")) or "rubro:" in s_lower:
            cat = re.sub(r'.*?(rubro|categoría|categoria|familia|sección|seccion)\s*:\s*', '', s, flags=re.IGNORECASE).strip()
            return True, cat if cat else None

        # Row with very few cells and no numeric digits (e.g. single title banner)
        if len(str_cells) <= 2 and len(s) > 2 and not any(char.isdigit() for char in s):
            return True, s.strip()

    return False, None


def normalize_product_text(text: str) -> str:
    """Normalizes product descriptions for fuzzy/semantic catalog matching."""
    s = str(text or "").lower()
    # Replace Spanish accents
    s = s.replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
    # Standardize liquid and volume measures
    s = re.sub(r'1[\.,]5\s*(l|lt|lts|litro|litros)\b', '1500cc', s)
    s = re.sub(r'2[\.,]25\s*(l|lt|lts|litro|litros)\b', '2250cc', s)
    s = re.sub(r'2[\.,]5\s*(l|lt|lts|litro|litros)\b', '2500cc', s)
    s = re.sub(r'1\s*(l|lt|lts|litro|litros)\b', '1000cc', s)
    s = re.sub(r'(\d+)\s*(l|lt|lts|litro|litros)\b', r'\g<1>000cc', s)
    # Standardize weight measures
    s = re.sub(r'1\s*(kg|kilo|kilos)\b', '1000g', s)
    s = re.sub(r'(\d+)\s*gr(s)?\b', r'\1g', s)
    s = re.sub(r'(\d+)\s*cc\b', r'\1cc', s)
    # Strip punctuation
    s = re.sub(r'[^\w\s]', ' ', s)
    # Remove packaging and noise stopwords
    noise_words = {
        'de', 'del', 'la', 'el', 'los', 'las', 'x', 'para', 'con', 'en', 'u', 'un',
        'botella', 'tetra', 'vidrio', 'lata', 'fardo', 'caja', 'pack', 'sabor',
        'original', 'tradicional', 'trigo', 'girasol', 'clasica', 'clasico', 'retornable'
    }
    tokens = [w for w in s.split() if w not in noise_words and len(w) > 1]
    return ' '.join(tokens)


class CatalogService:
    def __init__(self):
        self.products: List[ProductItem] = []
        self.last_updated: Optional[datetime] = None
        self.source_info: str = "Empty"
        self.current_rubro: str = "Distribuidora Mayorista San Martín"

    def load_from_csv(self, csv_content: str, source_name: str = "CSV") -> int:
        """Parses CSV text into product catalog, ignoring banners and headers."""
        if not csv_content or not csv_content.strip():
            return 0

        first_line = csv_content.strip().split("\n")[0]
        delimiter = ";" if ";" in first_line else ","

        reader = csv.reader(io.StringIO(csv_content.strip()), delimiter=delimiter)
        rows = list(reader)
        if not rows:
            return 0

        header_idx, col_map = find_header_and_mapping(rows)
        current_category = "General"

        items: List[ProductItem] = []
        for row in rows[header_idx + 1:]:
            if not row or not any(row):
                continue

            name_idx = col_map["name"]
            price_idx = col_map["price"]

            is_divider, section_cat = extract_section_category(list(row), name_idx)
            if is_divider:
                if section_cat:
                    current_category = section_cat
                continue

            if name_idx is None or name_idx >= len(row):
                continue

            raw_name = str(row[name_idx]).strip()
            if not raw_name:
                continue

            raw_price = row[price_idx] if (price_idx is not None and price_idx < len(row)) else 0.0
            price = clean_price(raw_price)

            if price <= 0 and not any(str(c or "").strip() for i, c in enumerate(row) if i != name_idx):
                continue

            presentation = "Unidad"
            if col_map["presentation"] is not None and col_map["presentation"] < len(row):
                p_val = str(row[col_map["presentation"]]).strip()
                if p_val:
                    presentation = p_val

            category = current_category
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
        """Parses Excel workbook bytes into product catalog, scanning all visible sheets."""
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            items: List[ProductItem] = []

            for sheet in wb.worksheets:
                if getattr(sheet, "sheet_state", "visible") != "visible":
                    continue

                rows = list(sheet.iter_rows(values_only=True))
                if not rows or len(rows) < 2:
                    continue

                header_idx, col_map = find_header_and_mapping(rows)
                sheet_default_cat = sheet.title if sheet.title.lower() not in ["sheet1", "hoja1", "hoja 1", "datos", "productos"] else "General"
                current_category = sheet_default_cat

                for row in rows[header_idx + 1:]:
                    if not row or not any(row):
                        continue

                    name_idx = col_map["name"]
                    price_idx = col_map["price"]

                    is_divider, section_cat = extract_section_category(list(row), name_idx)
                    if is_divider:
                        if section_cat:
                            current_category = section_cat
                        continue

                    if name_idx is None or name_idx >= len(row):
                        continue

                    raw_name = str(row[name_idx] or "").strip()
                    if not raw_name:
                        continue

                    raw_price = row[price_idx] if (price_idx is not None and price_idx < len(row)) else 0.0
                    price = clean_price(raw_price)

                    if price <= 0 and not any(str(c or "").strip() for i, c in enumerate(row) if i != name_idx):
                        continue

                    presentation = "Unidad"
                    if col_map["presentation"] is not None and col_map["presentation"] < len(row):
                        p_val = str(row[col_map["presentation"]] or "").strip()
                        if p_val:
                            presentation = p_val

                    category = current_category
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

    async def load_from_pdf_bytes(self, content: bytes, filename: str = "Catalogo.pdf") -> int:
        """
        Uses Gemini Multimodal to extract products and prices from a supplier PDF catalog,
        handling multi-page documents, columns, tables, codes and prices.
        """
        import base64
        gemini_key = settings.GEMINI_API_KEY
        if not gemini_key:
            logger.warning("No Gemini API key for PDF parsing")
            return 0

        b64_pdf = base64.b64encode(content).decode("utf-8")
        prompt = (
            "Extraé todos los productos, artículos y materiales de esta lista de precios o catálogo en PDF.\n"
            "Por cada producto extraé en formato JSON una lista con estas claves exactas:\n"
            "- name: descripción o nombre del producto (ej: 'Martillo Galponero 20mm')\n"
            "- price: precio numérico (float, ej: 14500.0, sin signos $ ni puntos de miles)\n"
            "- code: código de artículo o SKU si figura (o null)\n"
            "- presentation: unidad o presentación (ej: 'Unidad', 'Caja x 100', 'Bolsa')\n"
            "- category: rubro o familia del producto (ej: 'Herramientas', 'Bulonería', 'Pinturas')\n"
            "Respondé ÚNICAMENTE un JSON con la clave 'products' conteniendo la lista de productos."
        )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={gemini_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"inline_data": {"mime_type": "application/pdf", "data": b64_pdf}},
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {"response_mime_type": "application/json"}
        }

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    cand = res.json().get("candidates", [])
                    if cand and "content" in cand[0]:
                        parts = cand[0]["content"].get("parts", [])
                        if parts:
                            data = json.loads(parts[0].get("text", "{}"))
                            raw_prods = data.get("products", [])
                            items: List[ProductItem] = []
                            for p in raw_prods:
                                n = str(p.get("name") or "").strip()
                                pr = float(p.get("price") or 0.0)
                                if n and pr > 0:
                                    items.append(ProductItem(
                                        name=n,
                                        price=pr,
                                        code=p.get("code"),
                                        presentation=p.get("presentation") or "Unidad",
                                        category=p.get("category") or "General",
                                        in_stock=True
                                    ))
                            if items:
                                self.products = items
                                self.last_updated = datetime.now(timezone.utc)
                                self.source_info = f"{filename} ({len(items)} productos)"
                                logger.info(f"Loaded {len(items)} products from PDF: {filename}")
                                return len(items)
        except Exception as e:
            logger.error(f"Error parsing PDF catalog with Gemini: {e}")
        return 0

    def export_to_excel(self, file_path: str):
        """Exports the active catalog to a beautifully formatted Excel workbook."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Catálogo Actualizado"

        headers = ["Código", "Producto", "Presentación", "Precio Unitario ($)", "Stock", "Categoría"]
        ws.append(headers)

        header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        thin_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="thin", color="CBD5E1"),
            bottom=Side(style="thin", color="CBD5E1")
        )

        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for r_idx, p in enumerate(self.products, start=2):
            row_data = [
                p.code or f"ART-{r_idx-1:03d}",
                p.name,
                p.presentation,
                p.price,
                "SI" if p.in_stock else "NO",
                p.category
            ]
            ws.append(row_data)
            for c_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=r_idx, column=c_idx)
                cell.border = thin_border
                if c_idx == 4:
                    cell.number_format = "$#,##0"
                    cell.alignment = Alignment(horizontal="right")
                elif c_idx in [1, 5]:
                    cell.alignment = Alignment(horizontal="center")

        ws.column_dimensions["A"].width = 14
        ws.column_dimensions["B"].width = 34
        ws.column_dimensions["C"].width = 18
        ws.column_dimensions["D"].width = 20
        ws.column_dimensions["E"].width = 12
        ws.column_dimensions["F"].width = 18

        wb.save(file_path)

    def update_from_supplier_excel(
        self,
        content: bytes,
        filename: str = "proveedor.xlsx",
        export_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Cross-references an incoming supplier Excel sheet with the active product catalog.
        Matches by SKU code or fuzzy semantic description, updates catalog prices in-place,
        detects new supplier products, generates an updated catalog .xlsx, and returns an executive report.
        """
        import os
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            supplier_items: List[ProductItem] = []

            for sheet in wb.worksheets:
                if getattr(sheet, "sheet_state", "visible") != "visible":
                    continue
                rows = list(sheet.iter_rows(values_only=True))
                if not rows or len(rows) < 2:
                    continue

                header_idx, col_map = find_header_and_mapping(rows)
                for row in rows[header_idx + 1:]:
                    if not row or not any(row):
                        continue
                    name_idx = col_map["name"]
                    price_idx = col_map["price"]
                    if name_idx is None or name_idx >= len(row):
                        continue

                    is_divider, _ = extract_section_category(list(row), name_idx)
                    if is_divider:
                        continue

                    raw_name = str(row[name_idx] or "").strip()
                    if not raw_name:
                        continue

                    raw_price = row[price_idx] if (price_idx is not None and price_idx < len(row)) else 0.0
                    price = clean_price(raw_price)
                    if price <= 0:
                        continue

                    code = None
                    if col_map["code"] is not None and col_map["code"] < len(row):
                        cd = str(row[col_map["code"]] or "").strip()
                        if cd:
                            code = cd

                    supplier_items.append(ProductItem(name=raw_name, price=price, code=code))

            if not supplier_items:
                return {
                    "status": "error",
                    "matched_count": 0,
                    "new_count": 0,
                    "whatsapp_message": f"⚠️ No se encontraron productos válidos con precio en el archivo `{filename}`."
                }

            matched_items: List[Dict[str, Any]] = []
            new_items: List[ProductItem] = []

            for sup in supplier_items:
                norm_sup = normalize_product_text(sup.name)
                sup_tokens = set(norm_sup.split())

                best_match: Optional[ProductItem] = None
                best_score = 0.0

                # 1. Exact code match
                if sup.code:
                    clean_sup_code = re.sub(r'[^\w]', '', sup.code).lower()
                    for p in self.products:
                        if p.code and re.sub(r'[^\w]', '', p.code).lower() == clean_sup_code:
                            best_match = p
                            best_score = 1.0
                            break

                # 2. Semantic fuzzy match
                if not best_match:
                    for p in self.products:
                        norm_p = normalize_product_text(p.name)
                        p_tokens = set(norm_p.split())
                        if not sup_tokens or not p_tokens:
                            continue

                        intersection = len(sup_tokens & p_tokens)
                        union = len(sup_tokens | p_tokens)
                        jaccard = intersection / union if union > 0 else 0
                        seq = SequenceMatcher(None, norm_sup, norm_p).ratio()
                        score = 0.6 * jaccard + 0.4 * seq

                        # If brand & volume match perfectly, boost score
                        if intersection >= 2 and score >= 0.55:
                            score = max(score, 0.80)

                        if score > best_score:
                            best_score = score
                            best_match = p

                if best_match and best_score >= 0.60:
                    old_price = best_match.price
                    new_price = sup.price
                    diff = new_price - old_price
                    pct = ((diff / old_price) * 100) if old_price > 0 else 0.0

                    best_match.price = new_price
                    matched_items.append({
                        "product": best_match.name,
                        "presentation": best_match.presentation,
                        "old_price": old_price,
                        "new_price": new_price,
                        "diff": diff,
                        "pct": pct
                    })
                else:
                    new_items.append(sup)

            self.last_updated = datetime.now(timezone.utc)

            # Export updated catalog Excel
            if export_path is None:
                export_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "catalogo_actualizado.xlsx")
            export_path = os.path.abspath(export_path)
            os.makedirs(os.path.dirname(export_path), exist_ok=True)
            self.export_to_excel(export_path)

            # Build WhatsApp message
            lines = [
                f"📊 *¡Actualización de Proveedor Procesada!*",
                f"📁 *Archivo:* `{filename}`\n",
                f"✅ *{len(matched_items)} productos actualizados* con nuevo precio.",
            ]
            if new_items:
                lines.append(f"📦 *{len(new_items)} productos nuevos* detectados en la lista del proveedor.")
            lines.append("⚡ *Sofía ya está cotizando con estos nuevos precios.*\n")

            if matched_items:
                lines.append("📈 *Detalle de Aumentos:*")
                for item in matched_items:
                    old_f = f"${int(item['old_price']):,}".replace(",", ".")
                    new_f = f"${int(item['new_price']):,}".replace(",", ".")
                    sign = "+" if item['pct'] >= 0 else ""
                    lines.append(f"• *{item['product']}*: {old_f} ➔ *{new_f}* ({sign}{item['pct']:.1f}%)")
                lines.append("")

            if new_items:
                lines.append("✨ *Nuevos ítems detectados:*")
                for ni in new_items[:5]:
                    price_f = f"${int(ni.price):,}".replace(",", ".")
                    lines.append(f"• *{ni.name}*: {price_f}")
                if len(new_items) > 5:
                    lines.append(f"• ... y {len(new_items) - 5} más.")
                lines.append("")

            lines.append("📥 *Descargá tu catálogo actualizado:*")
            lines.append("https://sofia-ai-agency.onrender.com/assets/catalogo_actualizado.xlsx")

            msg = "\n".join(lines)
            return {
                "status": "success",
                "matched_count": len(matched_items),
                "new_count": len(new_items),
                "matched_items": matched_items,
                "new_items": new_items,
                "excel_path": export_path,
                "excel_url": "https://sofia-ai-agency.onrender.com/assets/catalogo_actualizado.xlsx",
                "whatsapp_message": msg
            }
        except Exception as e:
            logger.error(f"Error updating from supplier Excel: {e}")
            return {
                "status": "error",
                "matched_count": 0,
                "new_count": 0,
                "whatsapp_message": f"❌ Ocurrió un error al procesar la lista del proveedor `{filename}`: {str(e)}"
            }

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

        stopwords = {
            "de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o",
            "me", "te", "se", "nos", "les", "con", "sin", "por", "para", "en",
            "mandas", "mandás", "traes", "traés", "mandame", "mándame", "quiero", "necesito"
        }
        # Strip punctuation from query words
        raw_tokens = [re.sub(r'[^\w\s]', '', t).strip().lower() for t in query.split()]
        tokens = [t for t in raw_tokens if len(t) >= 3 and t not in stopwords]
        if not tokens:
            return []

        matches = []
        for p in self.products:
            name_lower = p.name.lower()
            category_lower = p.category.lower()
            if all(re.search(rf'\b{re.escape(t)}', name_lower) or re.search(rf'\b{re.escape(t)}', category_lower) for t in tokens):
                matches.append(p)
            elif any(re.search(rf'\b{re.escape(t)}', name_lower) for t in tokens):
                matches.append(p)

        matches.sort(key=lambda p: (not p.in_stock, not (query.lower() in p.name.lower())))
        return matches[:limit]

    def find_product_exact_or_best(self, name_or_code: str) -> Optional[ProductItem]:
        """Finds closest product match by code or name."""
        if not name_or_code:
            return None
        clean_target = re.sub(r'[^\w\s]', '', name_or_code).strip().lower()

        for p in self.products:
            if p.code and re.sub(r'[^\w\s]', '', p.code).strip().lower() == clean_target:
                return p

        for p in self.products:
            if re.sub(r'[^\w\s]', '', p.name).strip().lower() == clean_target:
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

    def set_rubro(self, rubro: str) -> Tuple[str, int]:
        """
        Switches the active catalog and merchant profile to a specific commercial trade:
        - 'ferreteria': Tools, screws, abrasives, paints, fixings
        - 'kiosco': Candies, chocolates, drinks, snacks, cigarettes
        - 'distribuidora': Wholesale food, beverages, dairy, bulk items
        """
        clean_r = rubro.lower().strip()
        items: List[ProductItem] = []
        trade_title = ""

        if "ferret" in clean_r or "herramient" in clean_r:
            trade_title = "Ferretería & Bazar Industrial"
            ferreteria_catalog = [
                ("Tornillos autoperforantes 1 pulgada", 8500.0, "Caja x 1000", "Tornillería"),
                ("Tornillos tirafondo 1/4 x 2", 7200.0, "Caja x 100", "Tornillería"),
                ("Tarugos con tope N°8", 3200.0, "Bolsa x 100", "Fijación"),
                ("Disco de corte amoladora 115mm x 1mm", 1400.0, "Unidad", "Abrasivos"),
                ("Disco de desbaste metal 115mm", 2800.0, "Unidad", "Abrasivos"),
                ("Disco diamantado continuo 115mm", 6500.0, "Unidad", "Abrasivos"),
                ("Amoladora angular 115mm 850W", 68000.0, "Unidad", "Herramientas Eléctricas"),
                ("Taladro percutor 13mm 650W", 74000.0, "Unidad", "Herramientas Eléctricas"),
                ("Destornillador Phillips 6x100mm", 4800.0, "Unidad", "Herramientas Manuales"),
                ("Destornillador Plano 6x100mm", 4500.0, "Unidad", "Herramientas Manuales"),
                ("Juego de destornilladores x 6 piezas", 18500.0, "Set", "Herramientas Manuales"),
                ("Martillo galponero mango fibra 500g", 14500.0, "Unidad", "Herramientas Manuales"),
                ("Pinza universal 8 pulgadas aislada", 12500.0, "Unidad", "Herramientas Manuales"),
                ("Alicate corte diagonal 6 pulgadas", 11000.0, "Unidad", "Herramientas Manuales"),
                ("Llave francesa ajustable 10 pulgadas", 16500.0, "Unidad", "Herramientas Manuales"),
                ("Cinta aisladora negra 20 metros", 1500.0, "Rollo", "Electricidad"),
                ("Cinta de teflón 3/4 x 20m", 950.0, "Rollo", "Plomería"),
                ("Thinner estándar 1 litro", 4200.0, "Botella", "Pinturas & Química"),
                ("Aguarrás mineral 1 litro", 3800.0, "Botella", "Pinturas & Química"),
                ("Sellador de silicona neutra transparente 280ml", 6800.0, "Tubo", "Adhesivos & Selladores"),
                ("Pegamento de contacto Poxiran 250cc", 5400.0, "Lata", "Adhesivos & Selladores"),
                ("Candado de bronce 40mm con 3 llaves", 8900.0, "Unidad", "Cerrajería"),
                ("Pintura látex interior blanco 4L", 22000.0, "Balde", "Pinturas & Química"),
                ("Lija al agua grano 180", 650.0, "Pliego", "Abrasivos")
            ]
            for name, price, pres, cat in ferreteria_catalog:
                items.append(ProductItem(name=name, price=price, presentation=pres, category=cat, in_stock=True))

        elif "kiosc" in clean_r or "almacen" in clean_r or "almacén" in clean_r:
            trade_title = "Kiosco & Almacén 'Lo de Juan'"
            kiosco_catalog = [
                ("Alfajor Guaymallén chocolate", 18000.0, "Caja x 40", "Golosinas"),
                ("Alfajor Jorgito blanco", 16800.0, "Caja x 24", "Golosinas"),
                ("Alfajor Havanna clásico", 24000.0, "Caja x 12", "Golosinas"),
                ("Chocolate Milka Leger 45g", 28800.0, "Caja x 24", "Chocolates"),
                ("Chicles Beldent menta", 12000.0, "Caja x 20", "Golosinas"),
                ("Caramelos Sugus surtidos 500g", 4500.0, "Bolsa", "Golosinas"),
                ("Coca Cola 500ml", 8400.0, "Pack x 6", "Bebidas"),
                ("Coca Cola 1.5L", 14400.0, "Pack x 6", "Bebidas"),
                ("Sprite 1.5L", 13800.0, "Pack x 6", "Bebidas"),
                ("Cerveza Quilmes clásica 473ml", 8100.0, "Pack x 6", "Bebidas"),
                ("Agua mineral Villavicencio 500ml", 5400.0, "Pack x 6", "Bebidas"),
                ("Papas fritas Lays clásicas 85g", 18500.0, "Tira x 10", "Snacks"),
                ("Galletitas Oreo 118g", 7200.0, "Pack x 6", "Galletitas"),
                ("Cigarrillos Philip Morris Box 20", 3200.0, "Atado", "Tabaquería"),
                ("Encendedor Bic mini", 15600.0, "Blister x 12", "Varios")
            ]
            for name, price, pres, cat in kiosco_catalog:
                items.append(ProductItem(name=name, price=price, presentation=pres, category=cat, in_stock=True))

        else:
            trade_title = "Distribuidora Mayorista San Martín"
            dist_catalog = [
                ("Harina 000 Cañuelas", 18500.0, "Bolsa 25kg", "Harinas"),
                ("Aceite de Girasol Cañuelas", 16800.0, "Caja 12x900ml", "Aceites"),
                ("Fideos Guiseros Matarazzo", 11200.0, "Fardo 10x500g", "Pastas Secas"),
                ("Arroz Largo Fino Lucchetti", 14000.0, "Fardo 10x1kg", "Arroces"),
                ("Azúcar Ledesma clásica", 9800.0, "Fardo 10x1kg", "Endulzantes"),
                ("Leche Entera La Serenísima", 17400.0, "Caja 12x1L", "Lácteos"),
                ("Yerba Playadito suave", 38000.0, "Fardo 10x1kg", "Infusiones"),
                ("Cerveza Quilmes Clásica", 19500.0, "Cajón 12x1L", "Bebidas"),
                ("Coca Cola Original", 16500.0, "Pack 6x2.25L", "Bebidas"),
                ("Puré de Tomate Noel", 8900.0, "Caja 12x520g", "Conservas"),
                ("Galletitas Criollitas", 12500.0, "Caja 20x100g", "Galletitas")
            ]
            for name, price, pres, cat in dist_catalog:
                items.append(ProductItem(name=name, price=price, presentation=pres, category=cat, in_stock=True))

        self.products = items
        self.last_updated = datetime.now(timezone.utc)
        self.source_info = f"Preset {trade_title} ({len(items)} productos)"
        self.current_rubro = trade_title
        logger.info(f"Switched rubro to {trade_title} with {len(items)} items")
        return trade_title, len(items)


catalog_service = CatalogService()

# Auto-initialize with updated catalog if available, fallback to distribuidora or base
import os
_updated_excel = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "catalogo_actualizado.xlsx")
_distribuidora_excel = os.path.join(os.path.dirname(__file__), "..", "..", "catalogo_cliente_distribuidora.xlsx")
_default_csv = os.path.join(os.path.dirname(__file__), "..", "data", "sample_catalog.csv")

if os.path.exists(_updated_excel):
    try:
        with open(_updated_excel, "rb") as _f:
            catalog_service.load_from_excel_bytes(_f.read(), filename="Catálogo Actualizado")
    except Exception as _e:
        logger.warning(f"Could not load updated catalog: {_e}")
elif os.path.exists(_distribuidora_excel):
    try:
        with open(_distribuidora_excel, "rb") as _f:
            catalog_service.load_from_excel_bytes(_f.read(), filename="Catálogo Distribuidora")
    except Exception as _e:
        logger.warning(f"Could not load distribuidora catalog: {_e}")
elif os.path.exists(_default_csv):
    try:
        with open(_default_csv, "r", encoding="utf-8") as _f:
            catalog_service.load_from_csv(_f.read(), source_name="Catálogo Base")
    except Exception as _e:
        logger.warning(f"Could not load base catalog: {_e}")
