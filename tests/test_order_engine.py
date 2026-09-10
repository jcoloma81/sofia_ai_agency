import pytest
import os
from app.services.order_engine import parse_order_text, format_order_summary_message, is_order_confirmation, detect_order_intent
from app.services.catalog import catalog_service

@pytest.fixture(autouse=True)
def setup_catalog():
    csv_path = os.path.join(os.path.dirname(__file__), "..", "app", "data", "sample_catalog.csv")
    with open(csv_path, "r", encoding="utf-8") as f:
        catalog_service.load_from_csv(f.read(), source_name="Catálogo Base")
    yield

def test_detect_order_intent():
    assert detect_order_intent("Mandame 3 cajas de aceite") is True
    assert detect_order_intent("Anotame 2 fardos de harina por favor") is True
    assert detect_order_intent("Hola buenas tardes, ¿cómo están?") is False

def test_parse_order_with_digits():
    # Oil ($14.400) and Flour ($12.500)
    text = "Mandame 3 cajas de aceite y 2 fardos de harina"
    draft = parse_order_text(text)

    assert len(draft.items) == 2
    
    # 3x oil = 3 * 14400 = 43200
    oil_item = next(i for i in draft.items if "aceite" in i.product.name.lower())
    assert oil_item.quantity == 3
    assert oil_item.unit_price == 14400.0
    assert oil_item.subtotal == 43200.0

    # 2x flour = 2 * 12500 = 25000
    flour_item = next(i for i in draft.items if "harina" in i.product.name.lower())
    assert flour_item.quantity == 2
    assert flour_item.unit_price == 12500.0
    assert flour_item.subtotal == 25000.0

    # Total = 43200 + 25000 = 68200
    assert draft.total == 68200.0
    assert draft.formatted_total() == "$68.200"

def test_parse_order_with_spanish_words():
    # 2x Yerba ($38.000) = 76000
    text = "Anotame dos fardos de yerba"
    draft = parse_order_text(text)

    assert len(draft.items) == 1
    yerba_item = draft.items[0]
    assert yerba_item.quantity == 2
    assert yerba_item.unit_price == 38000.0
    assert yerba_item.subtotal == 76000.0
    assert draft.total == 76000.0

def test_out_of_stock_item_handling():
    # Oreo is marked Stock=NO in sample_catalog
    text = "Mandame 1 caja de aceite y 2 cajas de oreo"
    draft = parse_order_text(text)

    assert len(draft.items) == 2
    assert draft.has_out_of_stock is True

    oreo_item = next(i for i in draft.items if "oreo" in i.product.name.lower())
    assert oreo_item.in_stock is False
    assert oreo_item.subtotal == 0.0

    # Only oil is summed
    assert draft.total == 14400.0

    msg = format_order_summary_message(draft, contact_name="Carlos")
    assert "Carlos" in msg
    assert "$14.400" in msg
    assert "sin stock" in msg.lower()
    assert "Oreo" in msg

def test_order_confirmation_detection():
    assert is_order_confirmation("Sí dale, confirmalo") is True
    assert is_order_confirmation("mandalo") is True
    assert is_order_confirmation("listo perfecto") is True
    assert is_order_confirmation("no, cancelalo") is False

def test_conversational_filler_filter():
    from app.services.order_engine import is_conversational_filler
    assert is_conversational_filler("ml para para pedirte") is True
    assert is_conversational_filler("para pedirte") is True
    assert is_conversational_filler("te quería pedir") is True
    assert is_conversational_filler("un favor") is True
    assert is_conversational_filler("aceite") is False
    assert is_conversational_filler("fideo") is False
    assert is_conversational_filler("harina pureza") is False

@pytest.mark.asyncio
async def test_parse_stutter_audio_inquiry():
    from app.services.order_engine import parse_order_or_inquiry_with_ai, build_product_inquiry_reply
    phrase = "ml para para pedirte y bien necesitar fideo del más económico que tengas"
    analysis = await parse_order_or_inquiry_with_ai(phrase)

    # Must be classified as product inquiry, NOT an order with fake items!
    assert analysis.intent in ["product_inquiry", "other"]
    assert len(analysis.draft.items) == 0
    # Must NEVER put the stutter into unmatched products!
    for q in analysis.draft.unmatched_queries:
        assert "para para pedirte" not in q

    reply = build_product_inquiry_reply(analysis.inquired_products or ["fideo"], contact_name="Javier")
    assert "para para pedirte" not in reply
    assert "ml" not in reply
    assert "fideo" in reply.lower()
    assert "Javier" in reply
