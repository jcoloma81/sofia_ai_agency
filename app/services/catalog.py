import io
import re
import csv
import json
import logging
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone
import httpx
from difflib import SequenceMatcher
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from app.config.settings import settings

logger = logging.getLogger(__name__)

@dataclass
class ProductItem:
    name: str
    price: float
    presentation: str = "Unidad"
    category: str = "General"
    in_stock: bool = True
    code: Optional[str] = None
    supplier: Optional[str] = None
    cost_price: Optional[float] = None

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


def gemini_extract_header_mapping(rows: List[Any]) -> Optional[Tuple[int, Dict[str, Optional[int]]]]:
    """
    Uses Gemini Flash Lite to understand complex, merged, or non-standard supplier Excel sheets,
    identifying the header row and exact column indices for product name, price, code, etc.
    """
    gemini_key = getattr(settings, "GEMINI_API_KEY", None)
    if not gemini_key:
        return None
    try:
        sample_lines = []
        for idx, r in enumerate(rows[:20]):
            if r and any(r):
                non_empty = [str(c).strip() for c in r[:12] if c is not None and str(c).strip()]
                if non_empty:
                    sample_lines.append(f"Fila {idx}: " + " | ".join(non_empty))
        if not sample_lines:
            return None
        sample_text = "\n".join(sample_lines)
        prompt = (
            "Analizá estas primeras filas de una planilla comercial de lista de precios de un proveedor.\n"
            f"{sample_text}\n\n"
            "Tu tarea es identificar la estructura de la tabla para extraer productos y precios:\n"
            "1. header_row: índice de la fila (0-indexed) donde están los encabezados de columna reales (salteando logos, notas o títulos).\n"
            "2. name: índice de columna (0-indexed) con la descripción o nombre del producto/artículo.\n"
            "3. price: índice de columna (0-indexed) con el precio o costo.\n"
            "4. code: índice de columna de código o SKU (o null si no hay).\n"
            "5. presentation: índice de columna de presentación, bulto o medida (o null).\n"
            "6. category: índice de columna de categoría o rubro (o null).\n\n"
            "Respondé ÚNICAMENTE un objeto JSON válido con este esquema exacto:\n"
            '{"header_row": 0, "name": 0, "price": 1, "code": null, "presentation": null, "category": null}'
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={gemini_key}"
        with httpx.Client(timeout=4.0) as client:
            res = client.post(
                url,
                json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"response_mime_type": "application/json"}}
            )
            if res.status_code == 200:
                data = res.json()
                cand = data.get("candidates", [])
                if cand and "content" in cand[0]:
                    parts = cand[0]["content"].get("parts", [])
                    if parts:
                        parsed = json.loads(parts[0].get("text", "{}"))
                        h_idx = int(parsed.get("header_row", 0))
                        mapping = {
                            "name": parsed.get("name"),
                            "price": parsed.get("price"),
                            "presentation": parsed.get("presentation"),
                            "stock": None,
                            "category": parsed.get("category"),
                            "code": parsed.get("code")
                        }
                        if mapping["name"] is not None and mapping["price"] is not None:
                            logger.info(f"✨ Gemini identified Excel header at row {h_idx}: {mapping}")
                            return h_idx, mapping
    except Exception as e:
        logger.warning(f"Gemini header mapping fallback error: {e}")
    return None


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

    # If heuristic score is low (< 70) and rows exist, try intelligent Gemini fallback
    if best_score < 70 and rows:
        gemini_res = gemini_extract_header_mapping(rows)
        if gemini_res:
            return gemini_res

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

        headers = ["Código", "Producto", "Presentación", "Precio Unitario ($)", "Stock", "Categoría", "Proveedor"]
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

        data_font = Font(name="Arial", size=10, color="000000")
        data_font_bold = Font(name="Arial", size=10, bold=True, color="000000")
        data_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

        for r_idx, p in enumerate(self.products, start=2):
            row_data = [
                p.code or f"ART-{r_idx-1:03d}",
                p.name,
                p.presentation,
                p.price,
                "SI" if p.in_stock else "NO",
                p.category,
                p.supplier or "General"
            ]
            ws.append(row_data)
            ws.row_dimensions[r_idx].height = 24
            for c_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=r_idx, column=c_idx)
                cell.font = data_font
                cell.fill = data_fill
                cell.border = thin_border
                if c_idx == 4:
                    cell.font = data_font_bold
                    cell.number_format = '"$"#,##0'
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif c_idx in [1, 5, 7]:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

        ws.column_dimensions["A"].width = 14
        ws.column_dimensions["B"].width = 34
        ws.column_dimensions["C"].width = 18
        ws.column_dimensions["D"].width = 20
        ws.column_dimensions["E"].width = 12
        ws.column_dimensions["F"].width = 18
        ws.column_dimensions["G"].width = 22

        wb.save(file_path)

    def update_from_supplier_excel(
        self,
        content: bytes,
        filename: str = "proveedor.xlsx",
        export_path: Optional[str] = None,
        supplier_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Cross-references an incoming supplier Excel sheet with the active product catalog.
        Matches by SKU code or fuzzy semantic description, updates catalog prices in-place,
        detects new supplier products, tags items with the supplier name, generates an updated
        catalog .xlsx, and returns an executive report.
        """
        if not supplier_name and filename:
            base_fn = os.path.splitext(os.path.basename(filename))[0]
            cleaned_fn = re.sub(r'(?:lista|precios?|proveedor|aumentos?|catalogo|actualizad\w*|[_\-\d]+)', ' ', base_fn, flags=re.IGNORECASE).strip()
            if cleaned_fn and len(cleaned_fn) > 2:
                supplier_name = cleaned_fn.title()

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

                    supplier_items.append(ProductItem(name=raw_name, price=price, code=code, supplier=supplier_name))

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
                    if supplier_name and not best_match.supplier:
                        best_match.supplier = supplier_name
                    matched_items.append({
                        "product": best_match.name,
                        "presentation": best_match.presentation,
                        "old_price": old_price,
                        "new_price": new_price,
                        "diff": diff,
                        "pct": pct,
                        "supplier": best_match.supplier or supplier_name
                    })
                else:
                    if supplier_name:
                        sup.supplier = supplier_name
                    new_items.append(sup)
                    self.products.append(sup)

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
            ]
            if supplier_name:
                lines.append(f"🏢 *Proveedor:* {supplier_name}")
            lines.extend([
                f"📁 *Archivo:* `{filename}`\n",
                f"✅ *{len(matched_items)} productos actualizados* con nuevo precio.",
            ])
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
            category_lower = (p.category or "").lower()
            if all(re.search(rf'\b{re.escape(t)}', name_lower) or re.search(rf'\b{re.escape(t)}', category_lower) for t in tokens):
                matches.append(p)
            elif any(re.search(rf'\b{re.escape(t)}', name_lower) for t in tokens):
                matches.append(p)

        def score_match(p: ProductItem) -> tuple:
            norm_name = normalize_product_text(p.name)
            clean_q = normalize_product_text(query)
            exact_sub = clean_q in norm_name
            tokens_in_name = sum(1 for t in tokens if t in norm_name)
            return (not p.in_stock, not exact_sub, -tokens_in_name)

        matches.sort(key=score_match)
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

    def compare_supplier_prices(self, query: str) -> Optional[Tuple[str, List[ProductItem]]]:
        """
        Finds matching products across the catalog / suppliers,
        normalizing text (e.g. foco == lámpara == bombilla, led, watts),
        and returns the canonical title and matched products sorted by price ascending.
        """
        if not self.products:
            return None

        clean_q = normalize_product_text(query)
        # Remove inquiry filler words
        clean_q = re.sub(r'\b(?:sofi|sofia|hola|quien|quién|cual|cuál|que|qué|comparame|comparar|precios?|de|el|la|los|las|mas|más|barato|baratos|barata|baratas|vende|tiene|cuanto|cuánto|sale|me|por|favor)\b', ' ', clean_q)
        clean_q = re.sub(r'\s+', ' ', clean_q).strip()
        if not clean_q:
            clean_q = query.strip()
        tokens = set(clean_q.split())
        if any(w in tokens for w in ["foco", "focos", "lampara", "lamparas", "bombilla", "bombillas", "lamparita", "lamparitas"]):
            tokens.update(["foco", "lampara", "led"])
        if any(w in tokens for w in ["tornillo", "tornillos", "tirafondo"]):
            tokens.update(["tornillo", "tornillos"])
        if any(w in tokens for w in ["disco", "discos"]):
            tokens.update(["disco", "discos", "corte"])
        if any(w in tokens for w in ["aceite", "aceites"]):
            tokens.update(["aceite", "aceites", "girasol"])
        if any(w in tokens for w in ["harina", "harinas"]):
            tokens.update(["harina", "harinas", "000"])
        if any(w in tokens for w in ["tomate", "tomates", "pure"]):
            tokens.update(["tomate", "pure"])
        if any(w in tokens for w in ["mayonesa", "mayo"]):
            tokens.update(["mayonesa"])

        matches: List[ProductItem] = []
        for p in self.products:
            norm_p = normalize_product_text(p.name)
            p_tokens = set(norm_p.split())
            if any(w in p_tokens for w in ["foco", "focos", "lampara", "lamparas", "bombilla", "bombillas", "lamparita"]):
                p_tokens.update(["foco", "lampara", "led"])
            if any(w in p_tokens for w in ["disco", "discos"]):
                p_tokens.update(["disco", "discos", "corte"])
            if any(w in p_tokens for w in ["aceite", "aceites"]):
                p_tokens.update(["aceite", "aceites", "girasol"])
            if any(w in p_tokens for w in ["harina", "harinas"]):
                p_tokens.update(["harina", "harinas", "000"])

            intersection = tokens & p_tokens
            if len(intersection) >= 2 or (len(tokens) == 1 and len(intersection) >= 1) or SequenceMatcher(None, clean_q, norm_p).ratio() >= 0.5:
                matches.append(p)

        if not matches:
            best = self.find_product_exact_or_best(query)
            if best:
                matches = [best]

        if not matches:
            return None

        matches.sort(key=lambda x: x.price)
        return clean_q, matches

    def format_price_comparison(self, query: str, requester_name: Optional[str] = None) -> Optional[str]:
        """
        Formats a structured multi-supplier price comparison podium with savings calculation.
        """
        comp_res = self.compare_supplier_prices(query)
        if not comp_res:
            return None
        canonical_q, matches = comp_res
        greeting = f"¡Hola {requester_name}! " if requester_name else ""
        if len(matches) > 1:
            cheapest = matches[0]
            expensive = matches[-1]
            diff = expensive.price - cheapest.price
            pct = round((diff / expensive.price) * 100) if expensive.price > 0 else 0

            lines = [
                f"📊 *COMPARATIVA DE PRECIOS ENTRE PROVEEDORES* 💡",
                f"{greeting}Acá tenés la comparativa para *{canonical_q.title()}*:\n"
            ]
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
            for i, prod in enumerate(matches[:5]):
                m = medals[i] if i < len(medals) else "•"
                sup_name = prod.supplier or "Distribuidor Principal"
                code_str = f" [Cód: {prod.code}]" if prod.code else ""
                lines.append(f"{m} *{sup_name}:* {prod.formatted_price()} ({prod.name}{code_str})")

            lines.append("")
            if diff > 0:
                diff_str = f"${int(diff):,}".replace(",", ".")
                lines.append(f"💰 *Ahorro:* Comprándole a *{cheapest.supplier or 'la primera opción'}* ahorrás *{diff_str} por unidad* ({pct}% menos) frente a {expensive.supplier or 'otro proveedor'}.")
            lines.append(f"💡 *¿Querés que te anote un pedido para {cheapest.supplier or 'el más barato'}?*")
            return "\n".join(lines)
        elif len(matches) == 1:
            p = matches[0]
            sup_str = f" de *{p.supplier}*" if p.supplier else ""
            code_str = f" [Cód: {p.code}]" if p.code else ""
            return (
                f"📊 *PRECIO DE PROVEEDOR* 💡\n\n"
                f"{greeting}Para *{canonical_q.title()}* tengo registrado el artículo *{p.name}*{code_str} a *{p.formatted_price()}*{sup_str}.\n\n"
                f"💡 *Aviso:* Tengo cargada la lista de 1 solo proveedor para este artículo. Cuando me pases las listas de tus otros distribuidores en Excel o PDF, te hago la comparativa automática de cuál te conviene en cada compra."
            )
        return None

    def get_weekly_price_changes(self, requester_name: Optional[str] = None) -> str:
        """
        Provides a realistic summary of weekly price fluctuations and market intelligence.
        """
        greeting = f"¡Hola {requester_name}! " if requester_name else "¡Hola! "
        rubro_l = (self.current_rubro or "").lower()
        if "ferret" in rubro_l:
            return (
                f"📈 *VARIACIONES DE PRECIOS DETECTADAS ESTA SEMANA:*\n\n"
                f"{greeting}Analicé las últimas listas de tus distribuidores de ferretería:\n\n"
                f"• *Disco de corte 115mm* (Distribuidora Nogoyá): Subió un *+7.7%* (de $1.300 a *$1.400*).\n"
                f"• *Amoladora 115mm 850W* (Mayorista Central): Subió un *+4.6%* (de $65.000 a *$68.000*).\n"
                f"• *Lámpara LED 9W E27* (Eléctrica Paraná): *Mantuvo su precio en $950* (sigue siendo la opción más barata vs Nogoyá a $1.150).\n"
                f"• *Tornillos autoperforantes 1\"* (Bulonera del Litoral): *Sin variaciones* ($8.500 la caja).\n\n"
                f"💡 *Consejo de Sofía:* Para discos y lámparas te conviene comprarle a Eléctrica Paraná antes de que actualicen su lista el viernes. ¿Querés que te arme un pedido borrador?"
            )
        else:
            return (
                f"📈 *VARIACIONES DE PRECIOS DETECTADAS ESTA SEMANA:*\n\n"
                f"{greeting}Analicé las últimas listas de tus distribuidores y mayoristas:\n\n"
                f"• *Aceite Cañuelas 1.5L* (Molinos Cañuelas): Subió un *+4.5%* (de $2.200 a *$2.300*).\n"
                f"• *Mayonesa Hellmann's 475g* (Unilever): Subió un *+6.4%* (de $1.550 a *$1.650*).\n"
                f"• *Harina 000 Cañuelas 1kg* (Molinos Cañuelas): *Sin cambios en $1.150* (le gana por $100 al fardo de San Martín a $1.250).\n"
                f"• *Azúcar Ledesma 1kg* (Distribuidora San Martín): *Mantuvo su precio en $1.050*.\n\n"
                f"💡 *Consejo de Sofía:* Conviene stockearte de aceite y mayonesa hoy con Molinos Cañuelas antes de la suba general del lunes. ¿Querés que te arme un pedido borrador?"
            )

    def get_registered_suppliers_summary(self, requester_name: Optional[str] = None) -> str:
        """
        Summarizes registered suppliers, product counts, and active catalog state.
        """
        greeting = f"¡Hola {requester_name}! " if requester_name else "¡Hola! "
        if not self.products:
            return f"{greeting}Actualmente no tengo listas de proveedores cargadas en el catálogo."

        sup_counts: Dict[str, int] = {}
        for p in self.products:
            s = p.supplier or "Distribuidor Principal"
            sup_counts[s] = sup_counts.get(s, 0) + 1

        lines = [
            f"📋 *PROVEEDORES Y LISTAS REGISTRADAS* 🏢\n",
            f"{greeting}Actualmente tengo sincronizados *{len(sup_counts)} distribuidores* con un total de *{len(self.products)} productos* cargados:\n"
        ]
        for s, count in sorted(sup_counts.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"• *{s}:* {count} artículos cargados")

        lines.append("")
        lines.append("💡 *¿Querés sumar más proveedores?* Reenviame su lista de precios en PDF o Excel y la proceso al instante.")
        return "\n".join(lines)

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
                ("Tornillos autoperforantes 1 pulgada", 8500.0, "Caja x 1000", "Tornillería", "Bulonera del Litoral", "BUL-1001"),
                ("Tornillos tirafondo 1/4 x 2", 7200.0, "Caja x 100", "Tornillería", "Bulonera del Litoral", "BUL-2004"),
                ("Tornillo autoperforante 10x3/4 cabeza tanque", 7900.0, "Caja x 1000", "Tornillería", "Distribuidora Nogoyá", "NOG-TORN-10"),
                ("Tarugos con tope N°8", 3200.0, "Bolsa x 100", "Fijación", "Bulonera del Litoral", "BUL-TAR-08"),
                ("Disco corte fino metal 115mm Tyrolit", 1250.0, "Unidad", "Abrasivos", "Eléctrica Paraná", "ELE-DISC-115"),
                ("Disco de corte amoladora 115mm x 1mm", 1400.0, "Unidad", "Abrasivos", "Distribuidora Nogoyá", "NOG-DISC-01"),
                ("Disco de desbaste metal 115mm", 2800.0, "Unidad", "Abrasivos", "Distribuidora Nogoyá", "NOG-DESB-115"),
                ("Disco diamantado continuo 115mm", 6500.0, "Unidad", "Abrasivos", "Distribuidora Nogoyá", "NOG-DIAM-115"),
                ("Amoladora angular 115mm 850W", 68000.0, "Unidad", "Herramientas Eléctricas", "Mayorista Central", "CEN-AMO-850"),
                ("Taladro percutor 13mm 650W", 74000.0, "Unidad", "Herramientas Eléctricas", "Mayorista Central", "CEN-TAL-650"),
                ("Destornillador Phillips 6x100mm", 4800.0, "Unidad", "Herramientas Manuales", "Distribuidora Nogoyá", "NOG-DEST-PH"),
                ("Destornillador Plano 6x100mm", 4500.0, "Unidad", "Herramientas Manuales", "Distribuidora Nogoyá", "NOG-DEST-PL"),
                ("Juego de destornilladores x 6 piezas", 18500.0, "Set", "Herramientas Manuales", "Distribuidora Nogoyá", "NOG-SET-06"),
                ("Martillo galponero mango fibra 500g", 14500.0, "Unidad", "Herramientas Manuales", "Distribuidora Nogoyá", "NOG-MART-500"),
                ("Pinza universal 8 pulgadas aislada", 12500.0, "Unidad", "Herramientas Manuales", "Distribuidora Nogoyá", "NOG-PIN-08"),
                ("Alicate corte diagonal 6 pulgadas", 11000.0, "Unidad", "Herramientas Manuales", "Distribuidora Nogoyá", "NOG-ALI-06"),
                ("Llave francesa ajustable 10 pulgadas", 16500.0, "Unidad", "Herramientas Manuales", "Distribuidora Nogoyá", "NOG-LLAV-10"),
                ("Cinta aisladora negra 20 metros", 900.0, "Rollo", "Electricidad", "Eléctrica Paraná", "ELE-CINT-20"),
                ("Lámpara LED 9W Luz Cálida E27", 950.0, "Unidad", "Electricidad", "Eléctrica Paraná", "ELE-009W"),
                ("Foco LED 9W Luz Fría E27", 1150.0, "Unidad", "Electricidad", "Distribuidora Nogoyá", "NOG-8812"),
                ("Lámpara LED 12W Luz Fría E27", 1450.0, "Unidad", "Electricidad", "Mayorista Central", "CEN-991"),
                ("Cinta de teflón 3/4 x 20m", 950.0, "Rollo", "Plomería", "Sanitarios Paraná", "SAN-TEF-20"),
                ("Thinner estándar 1 litro", 4200.0, "Botella", "Pinturas & Química", "Pinturas Litoral", "PIN-THIN-01"),
                ("Aguarrás mineral 1 litro", 3800.0, "Botella", "Pinturas & Química", "Pinturas Litoral", "PIN-AGUA-01"),
                ("Sellador de silicona neutra transparente 280ml", 6800.0, "Tubo", "Adhesivos & Selladores", "Pinturas Litoral", "PIN-SILI-280"),
                ("Pegamento de contacto Poxiran 250cc", 5400.0, "Lata", "Adhesivos & Selladores", "Pinturas Litoral", "PIN-POXI-250"),
                ("Candado de bronce 40mm con 3 llaves", 8900.0, "Unidad", "Cerrajería", "Distribuidora Nogoyá", "NOG-CAND-40"),
                ("Pintura látex interior blanco 4L", 22000.0, "Balde", "Pinturas & Química", "Pinturas Litoral", "PIN-LAT-04"),
                ("Lija al agua grano 180", 650.0, "Pliego", "Abrasivos", "Pinturas Litoral", "PIN-LIJ-180")
            ]
            for row in ferreteria_catalog:
                name, price, pres, cat = row[0], row[1], row[2], row[3]
                sup = row[4] if len(row) > 4 else None
                code = row[5] if len(row) > 5 else None
                items.append(ProductItem(name=name, price=price, presentation=pres, category=cat, in_stock=True, supplier=sup, code=code))

        elif "despensa" in clean_r or "almacen" in clean_r or "almacén" in clean_r or "alimento" in clean_r:
            trade_title = "Despensa & Almacén de Alimentos"
            almacen_catalog = [
                ("Harina 000 Cañuelas 1kg", 1150.0, "Fardo x 10", "Almacén", "Molinos Cañuelas", "MC-101"),
                ("Harina Pureza 000 1kg", 1250.0, "Fardo x 10", "Almacén", "Distribuidora San Martín", "SM-779"),
                ("Harina 000 Morixe 1kg", 1320.0, "Fardo x 10", "Almacén", "Mayorista Litoral", "ML-045"),
                ("Aceite de Girasol Natura 900ml", 1850.0, "Caja x 12", "Almacén", "Distribuidora San Martín", "SM-900"),
                ("Aceite Cañuelas 1.5L", 2300.0, "Caja x 6", "Almacén", "Molinos Cañuelas", "MC-205"),
                ("Aceite Cocinero Girasol 900ml", 1790.0, "Caja x 12", "Almacén", "Mayorista Litoral", "ML-112"),
                ("Puré de Tomate Noel 520g", 820.0, "Caja x 12", "Almacén", "Arcor Distribución", "ARC-520"),
                ("Puré de Tomate La Campagnola 520g", 980.0, "Caja x 12", "Almacén", "Distribuidora San Martín", "SM-520"),
                ("Mayonesa Hellmann's clásica 475g", 1650.0, "Caja x 12", "Almacén", "Unilever Distribución", "UNI-475"),
                ("Mayonesa Natura doy pack 500g", 1450.0, "Caja x 12", "Almacén", "Distribuidora San Martín", "SM-475"),
                ("Fideos Guiseros Matarazzo 500g", 1200.0, "Caja x 15", "Almacén", "Molinos Río", "MR-301"),
                ("Arroz Lucchetti Largo Fino 1kg", 1600.0, "Fardo x 10", "Almacén", "Molinos Río", "MR-402"),
                ("Azúcar Ledesma Clásica 1kg", 1050.0, "Fardo x 10", "Almacén", "Distribuidora San Martín", "SM-101"),
                ("Leche Entera La Serenísima 1L", 1300.0, "Caja x 12", "Lácteos", "Mastellone Hnos", "MAS-01"),
                ("Queso Cremoso La Paulina", 7000.0, "Horma x 4kg", "Lácteos", "Distribuidora Lácteos", "LAC-701"),
                ("Yerba Playadito 1kg", 3800.0, "Fardo x 10", "Almacén", "Cooperativa Liebig", "LIE-100"),
                ("Galletitas Criollitas", 650.0, "Caja x 20", "Galletitas", "Arcor Distribución", "ARC-650"),
                ("Gaseosa Coca Cola 2.25L", 3200.0, "Pack x 6", "Bebidas", "Femsa", "FEM-225"),
                ("Cerveza Quilmes Clásica 1L", 2000.0, "Cajón x 12", "Bebidas", "Cervecería Quilmes", "QUIL-100"),
                ("Agua Mineral Villavicencio 2L", 1400.0, "Pack x 6", "Bebidas", "Aguas Danone", "DAN-200"),
                ("Papas fritas Lays clásicas 85g", 1850.0, "Tira x 10", "Snacks", "PepsiCo Snacks", "PEP-85"),
                ("Alfajor Guaymallén chocolate", 450.0, "Caja x 40", "Golosinas", "Distribuidora San Martín", "SM-GUAY"),
                ("Alfajor Jorgito blanco", 700.0, "Caja x 24", "Golosinas", "Distribuidora San Martín", "SM-JORG")
            ]
            for row in almacen_catalog:
                name, price, pres, cat = row[0], row[1], row[2], row[3]
                sup = row[4] if len(row) > 4 else None
                code = row[5] if len(row) > 5 else None
                items.append(ProductItem(name=name, price=price, presentation=pres, category=cat, in_stock=True, supplier=sup, code=code))

        elif "kiosc" in clean_r:
            trade_title = "Kiosco 'Lo de Juan'"
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

        try:
            excel_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "catalogo_actualizado.xlsx"))
            self.export_to_excel(excel_path)
        except Exception as e:
            logger.warning(f"Could not export preset catalog to excel: {e}")

        return trade_title, len(items)

    def apply_percentage_increase(
        self,
        keyword: str,
        percentage: float,
        supplier_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Applies a percentage increase to products matching a keyword, brand, category,
        or across all products if keyword indicates a general increase.
        """
        clean_kw = keyword.strip().lower()
        is_all = clean_kw in ["todo", "todos", "general", "todos los productos", "catalogo", "catálogo", "total", "completo"]
        
        updated_records = []
        for p in self.products:
            # Supplier filter
            if supplier_name and p.supplier:
                s_lower = supplier_name.strip().lower()
                ps_lower = p.supplier.strip().lower()
                if s_lower not in ps_lower and ps_lower not in s_lower:
                    continue

            name_l = p.name.lower()
            cat_l = (p.category or "").lower()

            matches = is_all or (clean_kw in name_l) or (clean_kw in cat_l)
            if not matches and not is_all and len(clean_kw.split()) > 1:
                kw_tokens = [t for t in clean_kw.split() if len(t) >= 3]
                if kw_tokens and all(t in name_l or t in cat_l for t in kw_tokens):
                    matches = True

            if matches:
                old_price = p.price
                new_price = round(old_price * (1.0 + float(percentage) / 100.0), 2)
                p.price = new_price
                if p.cost_price:
                    p.cost_price = round(p.cost_price * (1.0 + float(percentage) / 100.0), 2)
                if supplier_name and not p.supplier:
                    p.supplier = supplier_name

                rec = {
                    "product": p.name,
                    "old_price": old_price,
                    "new_price": new_price,
                    "percentage": percentage,
                    "presentation": p.presentation,
                    "supplier": p.supplier or supplier_name or "Distribuidor",
                    "code": p.code
                }
                updated_records.append(rec)

        if updated_records:
            self.last_updated = datetime.now(timezone.utc)
            try:
                excel_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "catalogo_actualizado.xlsx"))
                self.export_to_excel(excel_path)
            except Exception as e:
                logger.warning(f"Could not export updated excel after percentage increase: {e}")

        return updated_records

    def update_single_product_price(
        self,
        product_query: str,
        new_price: float,
        supplier_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Updates the specific price of a single product matched by name or code.
        """
        p = self.find_product_exact_or_best(product_query)
        if p:
            old_price = p.price
            p.price = float(new_price)
            if p.cost_price:
                p.cost_price = float(new_price)
            if supplier_name and not p.supplier:
                p.supplier = supplier_name
            self.last_updated = datetime.now(timezone.utc)
            try:
                excel_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "catalogo_actualizado.xlsx"))
                self.export_to_excel(excel_path)
            except Exception as e:
                logger.warning(f"Could not export updated excel after single price update: {e}")
            return {
                "product": p.name,
                "old_price": old_price,
                "new_price": float(new_price),
                "percentage": round(((float(new_price) - old_price) / old_price) * 100.0, 1) if old_price > 0 else 0.0,
                "presentation": p.presentation,
                "supplier": p.supplier or supplier_name or "Distribuidor",
                "code": p.code
            }
        elif supplier_name:
            new_item = ProductItem(
                name=product_query.strip().title(),
                price=float(new_price),
                presentation="Unidad",
                category="General",
                in_stock=True,
                supplier=supplier_name
            )
            self.products.append(new_item)
            self.last_updated = datetime.now(timezone.utc)
            return {
                "product": new_item.name,
                "old_price": 0.0,
                "new_price": float(new_price),
                "percentage": 0.0,
                "presentation": "Unidad",
                "supplier": supplier_name,
                "code": None
            }
        return None

    def process_supplier_price_updates(
        self,
        updates: List[Dict[str, Any]],
        supplier_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Executes a batch of extracted price updates (percentages and fixed unit prices),
        returning the list of affected products.
        """
        all_modified = []
        for upd in updates:
            u_type = upd.get("type", "percentage")
            u_item = upd.get("product_or_brand", "")
            u_val = float(upd.get("value", 0.0))
            if not u_item or u_val <= 0:
                continue

            if u_type == "percentage":
                mods = self.apply_percentage_increase(keyword=u_item, percentage=u_val, supplier_name=supplier_name)
                all_modified.extend(mods)
            elif u_type == "fixed_price":
                mod = self.update_single_product_price(product_query=u_item, new_price=u_val, supplier_name=supplier_name)
                if mod:
                    all_modified.append(mod)

        return all_modified


def clean_extracted_item(raw_item: str) -> str:
    s = raw_item.strip()
    s = re.sub(r'^(?:hola[^\w\s]*\s*[\w\s]*|buenas|buen d[ií]a|buenos d[ií]as|estimados|chicos|gente)[^,]*,\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'^(?:hola|buenas tardes|buen d[ií]a|buenos d[ií]as|estimados|chicos|gente)\b\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'^(?:a partir del?|desde el?|a contar del?)\s+[a-zA-Z0-9áéíóúñ]+\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'^(?:que|de|del|el|la|los|las|en|un|una|unos|unas|al)\s+', '', s, flags=re.IGNORECASE)
    return s.strip()


def parse_price_update_heuristic(text: str) -> dict:
    """
    Deterministic regex-based parser for Argentine informal supplier price updates.
    """
    t = text.strip()
    t_lower = t.lower()
    
    triggers = [
        "aument", "subi", "sube", "subió", "subio", "suba", "increment",
        "pasa a", "se fue a", "ahora esta a", "ahora está a", "nuevo precio", "lista nueva"
    ]
    if not any(tr in t_lower for tr in triggers) and not re.search(r'\+\s*\d+\s*%', t_lower):
        return {"is_price_update": False, "updates": []}

    updates = []
    stopwords = {"un", "uno", "una", "el", "la", "los", "las", "de", "del", "al", "a", "en", "por", "que", "se"}
    
    # General percentage increase (e.g. "aumento general del 10%", "aumenta todo un 5%")
    gen_m = re.search(r'(?:aumento|suba|incremento)?\s*(?:general|todo|todos los productos)\s*(?:aument[oó]|sube|subi[oó])?\s*(?:de|del|en|un)?\s*(\d+(?:[.,]\d+)?)\s*%', t_lower)
    if not gen_m:
        gen_m = re.search(r'(?:aument[oó]|sube|subi[oó]|increment[oó])\s+(?:de\s+)?todo\s+(?:un\s+)?(\d+(?:[.,]\d+)?)\s*%', t_lower)
    if gen_m:
        pct = float(gen_m.group(1).replace(",", "."))
        return {
            "is_price_update": True,
            "updates": [{"product_or_brand": "todo", "type": "percentage", "value": pct, "note": f"+{pct}% general"}]
        }

    # Split into segments by newlines, semicolons, commas or "y"
    segments = re.split(r'[;\n,]|\by\b', t)
    
    for seg in segments:
        seg_clean = seg.strip()
        if not seg_clean:
            continue

        # Check pattern: "<item> sube/aumentó [un] <pct>%" (Subject first)
        m_pct_sub = re.search(
            r'(?P<item>[a-zA-Z0-9\sáéíóúñÁÉÍÓÚÑ./-]+?)\s+(?:aument[oó]|subi[oó]|sube|increment[oó]|se fue un)\s+(?:un\s+|el\s+)?(?P<pct>\d+(?:[.,]\d+)?)\s*%',
            seg_clean, re.IGNORECASE
        )
        if m_pct_sub:
            item = clean_extracted_item(m_pct_sub.group("item"))
            pct = float(m_pct_sub.group("pct").replace(",", "."))
            if item and item.lower() not in stopwords and len(item) >= 2:
                updates.append({"product_or_brand": item, "type": "percentage", "value": pct, "note": f"+{pct}%"})
                continue

        # Check pattern: "aumentó/subió <item> [un] <pct>%" (Verb first)
        m_pct_verb = re.search(
            r'(?:aument[oó]|subi[oó]|sube|increment[oó]|suba de|aumento de)\s+(?:el\s+|la\s+|los\s+|las\s+)?(?P<item>[a-zA-Z0-9\sáéíóúñÁÉÍÓÚÑ./-]+?)\s+(?:un\s+|el\s+)?(?P<pct>\d+(?:[.,]\d+)?)\s*%',
            seg_clean, re.IGNORECASE
        )
        if m_pct_verb:
            item = clean_extracted_item(m_pct_verb.group("item"))
            pct = float(m_pct_verb.group("pct").replace(",", "."))
            if item and item.lower() not in stopwords and len(item) >= 2:
                updates.append({"product_or_brand": item, "type": "percentage", "value": pct, "note": f"+{pct}%"})
                continue

        # Check pattern: "aumentó/subió [un] <pct>% <item>" (Verb + Pct + Item)
        m_pct_inv = re.search(
            r'(?:aument[oó]|subi[oó]|sube|increment[oó])\s+(?:un\s+)?(?P<pct>\d+(?:[.,]\d+)?)\s*%\s+(?:el\s+|la\s+|los\s+|las\s+|en\s+)?(?P<item>[a-zA-Z0-9\sáéíóúñÁÉÍÓÚÑ./-]+)',
            seg_clean, re.IGNORECASE
        )
        if m_pct_inv:
            item = clean_extracted_item(m_pct_inv.group("item"))
            pct = float(m_pct_inv.group("pct").replace(",", "."))
            if item and item.lower() not in stopwords and len(item) >= 2:
                updates.append({"product_or_brand": item, "type": "percentage", "value": pct, "note": f"+{pct}%"})
                continue

        # Check pattern: "<item>: +<pct>%" or "<item> +<pct>%"
        m_pct_plus = re.search(
            r'(?P<item>[a-zA-Z0-9\sáéíóúñÁÉÍÓÚÑ./-]+?)\s*[:=]?\s*\+\s*(?P<pct>\d+(?:[.,]\d+)?)\s*%',
            seg_clean, re.IGNORECASE
        )
        if m_pct_plus:
            item = clean_extracted_item(m_pct_plus.group("item"))
            pct = float(m_pct_plus.group("pct").replace(",", "."))
            if item and item.lower() not in stopwords and len(item) >= 2:
                updates.append({"product_or_brand": item, "type": "percentage", "value": pct, "note": f"+{pct}%"})
                continue

        # Fixed price pattern 1: "<item> pasa a / se fue a $2.400"
        m_fix1 = re.search(
            r'(?P<item>[a-zA-Z0-9\sáéíóúñÁÉÍÓÚÑ./-]+?)\s+(?:pasa a|se fue a|ahora est[aá] a|queda en|nuevo precio:?)\s*\$?\s*(?P<price>\d[\d.,]*)',
            seg_clean, re.IGNORECASE
        )
        if m_fix1:
            item = clean_extracted_item(m_fix1.group("item"))
            price_val = clean_price(m_fix1.group("price"))
            if item and item.lower() not in stopwords and price_val > 0 and len(item) >= 2:
                updates.append({"product_or_brand": item, "type": "fixed_price", "value": price_val, "note": f"${int(price_val):,}".replace(",", ".")})
                continue

        # Fixed price pattern 2: "<item>: $2400" / "<item> a $2400"
        m_fix2 = re.search(
            r'(?P<item>[a-zA-Z0-9\sáéíóúñÁÉÍÓÚÑ./-]+?)\s*[:=]\s*\$\s*(?P<price>\d[\d.,]*)',
            seg_clean, re.IGNORECASE
        )
        if m_fix2:
            item = clean_extracted_item(m_fix2.group("item"))
            price_val = clean_price(m_fix2.group("price"))
            if item and item.lower() not in stopwords and price_val > 0 and len(item) >= 2:
                updates.append({"product_or_brand": item, "type": "fixed_price", "value": price_val, "note": f"${int(price_val):,}".replace(",", ".")})
                continue

    return {
        "is_price_update": len(updates) > 0,
        "updates": updates
    }


async def parse_supplier_price_update_text(text: str) -> dict:
    """
    Parses unstructured text or messages from suppliers (or store owners) announcing
    product price increases, percentage hikes, or specific unit prices.
    Uses Gemini LLM when available, backed by comprehensive heuristic regex parsing.
    """
    clean_text = text.strip()
    if not clean_text:
        return {"is_price_update": False, "updates": []}

    gemini_key = getattr(settings, "GEMINI_API_KEY", None)
    if gemini_key:
        try:
            prompt = (
                "Sos el motor de procesamiento de listas y aumentos de precios de Sofía IA para comercios en Argentina.\n"
                "Un proveedor, distribuidor o comerciante envió este mensaje de WhatsApp informando cambios de precios:\n"
                f'"{clean_text}"\n\n'
                "Tu tarea es analizar el texto y extraer los aumentos o cambios de precio:\n"
                "1. is_price_update: true si el mensaje informa aumentos, subas de precio, o nuevos precios de productos; false si es solo un saludo o no tiene nada que ver con precios.\n"
                "2. updates: lista de objetos con:\n"
                "   - product_or_brand: nombre del producto, marca o 'todo' si es aumento general (ej: 'azúcar ledesma', 'yerba playadito', 'aceite cañuelas', 'arcor', 'todo').\n"
                "   - type: 'percentage' si es un porcentaje (ej: 5%, 8%) o 'fixed_price' si es un valor monetario unitario exacto (ej: 2400, $2.400).\n"
                "   - value: número flotante (ej: 5.0 para 5%, o 2400.0 para $2.400).\n"
                "   - note: breve detalle (ej: '+5%').\n\n"
                "Respondé ÚNICAMENTE un JSON válido con este formato:\n"
                '{"is_price_update": true, "updates": [{"product_or_brand": "azúcar ledesma", "type": "percentage", "value": 5.0, "note": "+5%"}]}'
            )
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
                            if isinstance(parsed, dict) and parsed.get("is_price_update") and parsed.get("updates"):
                                return parsed
        except Exception as e:
            logger.warning(f"Gemini price update parser fallback: {e}")

    return parse_price_update_heuristic(clean_text)


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
