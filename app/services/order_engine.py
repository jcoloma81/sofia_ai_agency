import re
import logging
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass, field
from app.services.catalog import catalog_service, ProductItem

logger = logging.getLogger(__name__)

SPANISH_NUMBER_WORDS = {
    "un": 1, "una": 1, "uno": 1,
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "veinte": 20, "veinticinco": 25, "treinta": 30, "cincuenta": 50, "cien": 100
}

@dataclass
class OrderItem:
    product: ProductItem
    quantity: int
    unit_price: float
    subtotal: float
    in_stock: bool = True

    def formatted_subtotal(self) -> str:
        if self.subtotal.is_integer():
            return f"${int(self.subtotal):,}".replace(",", ".")
        return f"${self.subtotal:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@dataclass
class OrderDraft:
    items: List[OrderItem] = field(default_factory=list)
    total: float = 0.0
    has_out_of_stock: bool = False
    unmatched_queries: List[str] = field(default_factory=list)

    def formatted_total(self) -> str:
        if self.total.is_integer():
            return f"${int(self.total):,}".replace(",", ".")
        return f"${self.total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def parse_order_text(text: str) -> OrderDraft:
    """
    Parses natural language order text into structured OrderDraft with exact calculations.
    Supports numbers (digits or words) and flexible product search.
    """
    if not text:
        return OrderDraft()

    # Remove agent name and conversational prefixes / verbs (with or without accents)
    cleaned = re.sub(
        r'\b(sofia|sofía|che|hola|buenas|buen d[ií]a|por favor|me\s+mandas|me\s+mandás|mandame|mándame|mandas|mandás|traeme|tráeme|traes|traés|pasame|pásame|pasas|pasás|cargame|cárgame|cargas|cargás|sumame|súmame|anotame|anótame|anota|anotá|quiero|necesito|pedir|pedido|agregame|agrégame|para mañana|para hoy|tenes|tenés)\b',
        '',
        text,
        flags=re.IGNORECASE
    )
    
    # Split by commas, 'y', 'e', or newlines
    raw_clauses = re.split(r'[,;\n]|\s+y\s+|\s+e\s+', cleaned)
    
    items: List[OrderItem] = []
    unmatched: List[str] = []
    has_out_of_stock = False

    for clause in raw_clauses:
        # Strip punctuation from clause
        clause = re.sub(r'[^\w\s]', ' ', clause).strip()
        if not clause or len(clause) < 2:
            continue

        # Extract quantity: look for digits or Spanish number words
        qty = 1
        num_match = re.search(r'\b(\d+)\b', clause)
        if num_match:
            qty = int(num_match.group(1))
            product_query = re.sub(r'\b\d+\b', '', clause).strip()
        else:
            word_found = False
            for word, val in SPANISH_NUMBER_WORDS.items():
                pattern = rf'\b{word}\b'
                if re.search(pattern, clause, re.IGNORECASE):
                    qty = val
                    product_query = re.sub(pattern, '', clause, flags=re.IGNORECASE).strip()
                    word_found = True
                    break
            if not word_found:
                product_query = clause

        # Clean packaging words from product query
        product_query = re.sub(r'\b(cajas?|fardos?|packs?|unidades?|bolsas?|cajones?|hormas?|kilos?|kg|de)\b', '', product_query, flags=re.IGNORECASE).strip()
        # Clean extra spaces
        product_query = re.sub(r'\s+', ' ', product_query).strip()

        if not product_query or len(product_query) < 2:
            continue

        # Look up product in catalog
        product = catalog_service.find_product_exact_or_best(product_query)
        if product:
            subtotal = product.price * qty if product.in_stock else 0.0
            if not product.in_stock:
                has_out_of_stock = True

            items.append(OrderItem(
                product=product,
                quantity=qty,
                unit_price=product.price,
                subtotal=subtotal,
                in_stock=product.in_stock
            ))
        else:
            unmatched.append(product_query)

    # Compute grand total
    total = sum(item.subtotal for item in items if item.in_stock)

    return OrderDraft(
        items=items,
        total=total,
        has_out_of_stock=has_out_of_stock,
        unmatched_queries=unmatched
    )


def format_order_summary_message(draft: OrderDraft, contact_name: Optional[str] = None) -> str:
    """
    Generates warm, crystal-clear order confirmation message for WhatsApp.
    """
    if not draft.items:
        return ""

    from app.services.brain import sanitize_contact_first_name
    safe_name = sanitize_contact_first_name(contact_name)
    saludo = f"¡Perfecto {safe_name}!" if safe_name else "¡Perfecto!"
    lines = [f"{saludo} Te paso el detalle de tu pedido:\n"]

    available_items = [it for it in draft.items if it.in_stock]
    out_items = [it for it in draft.items if not it.in_stock]

    for item in available_items:
        lines.append(f"• {item.quantity}x {item.product.name} ({item.product.presentation}): *{item.formatted_subtotal()}* ({item.product.formatted_price()} c/u)")

    lines.append(f"\n💰 *TOTAL ESTIMADO: {draft.formatted_total()}*")

    if out_items:
        lines.append("\n⚠️ *Aviso de stock:*")
        for item in out_items:
            lines.append(f"• {item.product.name}: Actualmente *sin stock*.")

    if draft.unmatched_queries:
        lines.append("\nℹ️ *Productos no identificados en catálogo:* " + ", ".join(draft.unmatched_queries))

    lines.append("\n🚚 *¿Te lo confirmo para ingresar el pedido a depósito y programar el reparto?*")
    return "\n".join(lines)


def detect_order_intent(text: str) -> bool:
    """Detects if message is an attempt to order products."""
    if not text:
        return False
    text_lower = text.lower()
    # Exclude price list / catalog requests from being parsed as product orders
    if any(k in text_lower for k in ["lista", "catalogo", "catálogo", "excel", "planilla", "precios"]):
        return False
    triggers = [
        "anotame", "anótame", "mandame", "mándame", "traeme", "tráeme", "pasame", "pásame",
        "cargame", "cárgame", "sumame", "súmame", "quiero pedir", "te pido",
        "hacer un pedido", "encargar", "hacerte un pedido", "necesito que me mandes",
        "cajas de", "fardos de", "packs de", "bolsas de", "cajones de"
    ]
    return any(t in text_lower for t in triggers)


def is_order_confirmation(text: str) -> bool:
    """Detects if customer says YES / confirm the order."""
    if not text:
        return False
    text_clean = text.lower().strip()
    words = re.findall(r'\b[a-záéíóúñ0-9]+\b', text_clean)
    if not words or len(words) > 7:
        return False

    # Never treat a commercial directive or inquiry as an order confirmation
    directive_words = {
        "minimo", "mínimo", "zona", "zonas", "flete", "precio", "cuanto", "cuánto",
        "horario", "horarios", "requisito", "requisitos", "directiva", "directivas", "regla", "reglas"
    }
    if any(w in directive_words for w in words):
        return False

    exact_confirmations = {
        "si", "sí", "dale", "confirmalo", "confirmá", "confirmar", "confirmado",
        "mandalo", "anotalo", "listo", "perfecto", "ok", "bueno", "metele", "avanza"
    }

    if any(w in exact_confirmations for w in words):
        return True

    joined = " ".join(words)
    phrases = [
        "si lo confirmo", "si confirmo", "si por favor", "si dale", "dale mandalo",
        "de acuerdo", "bueno dale", "dale perfecto", "dale dale", "mandalo nomas"
    ]
    return any(p in joined for p in phrases)
