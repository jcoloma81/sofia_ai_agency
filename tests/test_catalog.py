import io
import pytest
import openpyxl
from app.services.catalog import CatalogService, clean_price, clean_stock, ProductItem

def test_clean_price():
    assert clean_price("$ 14.400") == 14400.0
    assert clean_price("14.400,50") == 14400.50
    assert clean_price("$14,400.00") == 14400.0
    assert clean_price("12500") == 12500.0
    assert clean_price(None) == 0.0

def test_clean_stock():
    assert clean_stock("SI") is True
    assert clean_stock("disponible") is True
    assert clean_stock("NO") is False
    assert clean_stock("sin stock") is False
    assert clean_stock("0") is False

def test_load_from_csv():
    csv_sample = """Codigo;Producto;Presentacion;Precio;Stock;Categoria
ART01;Aceite Cañuelas 1.5L;Caja x 6;14.400;SI;Almacén
ART02;Galletitas Oreo;Caja x 24;26400;NO;Golosinas
ART03;Harina Pureza 000;Fardo x 10;12500,00;SI;Almacén"""

    service = CatalogService()
    count = service.load_from_csv(csv_sample)
    assert count == 3
    assert len(service.products) == 3

    # Product 1
    p1 = service.find_product_exact_or_best("aceite")
    assert p1 is not None
    assert p1.price == 14400.0
    assert p1.in_stock is True
    assert p1.formatted_price() == "$14.400"

    # Product 2 (out of stock)
    p2 = service.find_product_exact_or_best("oreo")
    assert p2 is not None
    assert p2.in_stock is False

    # Search
    results = service.search_products("almacén")
    assert len(results) == 2

def test_load_from_excel_bytes():
    # Create workbook in-memory
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Código", "Artículo", "Bulto", "Precio Venta", "Stock"])
    ws.append(["A1", "Cerveza Quilmes 1L", "Cajón x 12", 24000, "SI"])
    ws.append(["A2", "Coca Cola 2.25L", "Pack x 6", 19200, "SI"])

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)

    service = CatalogService()
    count = service.load_from_excel_bytes(stream.read())
    assert count == 2
    
    p = service.find_product_exact_or_best("quilmes")
    assert p is not None
    assert p.price == 24000.0
    assert p.presentation == "Cajón x 12"

def test_google_sheet_url_normalization():
    edit_url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0"
    export_url = CatalogService.normalize_google_sheet_url(edit_url)
    assert "export?format=csv&gid=0" in export_url
    assert "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms" in export_url
