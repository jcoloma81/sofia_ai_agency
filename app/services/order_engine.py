import re
import json
import logging
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass, field
import httpx
from app.services.catalog import catalog_service, ProductItem
from app.config.settings import settings

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


@dataclass
class OrderAnalysis:
    intent: str  # "order", "product_inquiry", "price_list_request", "other"
    draft: OrderDraft = field(default_factory=OrderDraft)
    inquired_products: List[str] = field(default_factory=list)
    cleaned_meaning: Optional[str] = None


def is_conversational_filler(text: str) -> bool:
    """Checks if a string is conversational chatter or audio artifact rather than a product name."""
    if not text:
        return True
    clean = text.lower().strip()
    if len(clean) < 3:
        return True
    filler_tokens = {
        "para", "pedirte", "pedir", "pedido", "necesitar", "necesito", "tengas", "tenes", "tenés",
        "consultar", "consulta", "averiguar", "queria", "quería", "mandar", "traer", "pasar",
        "bien", "hola", "che", "ml", "eh", "em", "favor", "gracias", "por", "que", "qué", "si", "sí",
        "de", "del", "mas", "más", "menos", "un", "una", "unos", "unas", "buen", "dia", "día",
        "buenas", "tardes", "noches", "cuanto", "cuánto", "precio", "precios", "stock", "como", "cómo",
        "estar", "estas", "estás", "estan", "están", "queria", "queremos", "queres", "querés"
    }
    words = set(re.findall(r'\b[a-záéíóúñ]+\b', clean))
    if not words or words.issubset(filler_tokens):
        return True
    non_fillers = [w for w in words if w not in filler_tokens and len(w) > 2]
    return len(non_fillers) == 0


def build_order_draft_from_entities(items_data: List[Dict[str, Any]]) -> OrderDraft:
    """
    Given structured entity items from Gemini NLU, resolves each product in catalog
    and computes exact math subtotals and grand totals in Python.
    """
    items: List[OrderItem] = []
    unmatched: List[str] = []
    has_out_of_stock = False

    for item_dict in items_data:
        raw_name = str(item_dict.get("product_name") or item_dict.get("product") or "").strip()
        if not raw_name or is_conversational_filler(raw_name):
            continue
        try:
            qty = int(item_dict.get("quantity") or 1)
            if qty <= 0:
                qty = 1
        except (ValueError, TypeError):
            qty = 1

        product = catalog_service.find_product_exact_or_best(raw_name)
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
            if not is_conversational_filler(raw_name):
                unmatched.append(raw_name)

    total = sum(it.subtotal for it in items if it.in_stock)
    return OrderDraft(
        items=items,
        total=total,
        has_out_of_stock=has_out_of_stock,
        unmatched_queries=unmatched
    )


def parse_order_text(text: str) -> OrderDraft:
    """
    Parses natural language order text into structured OrderDraft with exact calculations.
    Supports numbers (digits or words) and flexible product search.
    """
    if not text:
        return OrderDraft()

    # Remove agent name and conversational prefixes / verbs (with or without accents)
    cleaned = re.sub(
        r'\b(sofia|sofía|che|hola|buenas|buen d[ií]a|por favor|me\s+mandas|me\s+mandás|mandame|mándame|mandas|mandás|traeme|tráeme|traes|traés|pasame|pásame|pasas|pasás|cargame|cárgame|cargas|cargás|sumame|súmame|anotame|anótame|anota|anotá|quiero|necesito|pedir|pedido|agregame|agrégame|para mañana|para hoy|tenes|tenés|para\s+pedirte|te\s+quer[ií]a\s+pedir|te\s+pido|un\s+favor|para\s+para)\b',
        '',
        text,
        flags=re.IGNORECASE
    )
    cleaned = re.sub(r'^(ml\b|eh\b|em\b)+', '', cleaned.strip(), flags=re.IGNORECASE)
    
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

        if not product_query or len(product_query) < 2 or is_conversational_filler(product_query):
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
            if not is_conversational_filler(product_query):
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


def build_product_inquiry_reply(inquired_products: List[str], contact_name: Optional[str] = None) -> str:
    """
    Generates warm, human response when a customer inquires about stock/prices of products.
    """
    from app.services.brain import sanitize_contact_first_name
    safe_name = sanitize_contact_first_name(contact_name)
    saludo = f"¡Hola {safe_name}!" if safe_name else "¡Hola!"

    found_products: List[ProductItem] = []
    missing_queries: List[str] = []

    for q in inquired_products:
        p = catalog_service.find_product_exact_or_best(q)
        if p:
            found_products.append(p)
        else:
            if not is_conversational_filler(q):
                missing_queries.append(q)

    lines = []
    if found_products:
        lines.append(f"{saludo} Te paso los datos de lo que me consultás:\n")
        for p in found_products:
            stock_txt = f"*{p.formatted_price()}*" if p.in_stock else "*Sin stock momentáneo*"
            lines.append(f"• {p.name} ({p.presentation}): {stock_txt}")
        if missing_queries:
            clean_missing = ", ".join(f"*{m}*" for m in missing_queries)
            lines.append(f"\n⚠️ En cuanto a {clean_missing}, actualmente no lo tenemos en el catálogo de reparto.")
        lines.append("\n🚚 Si querés que te anote alguna cantidad para el reparto de mañana, avisame y te lo cargo al pedido.")
    else:
        clean_missing = ", ".join(f"*{m}*" for m in missing_queries) if missing_queries else "esos artículos"
        categories = sorted(list({p.category for p in catalog_service.products if p.category}))
        cat_str = ", ".join(categories) if categories else "alimentos, bebidas, lácteos y artículos de almacén"
        lines.append(
            f"{saludo} Disculpá, pero actualmente no trabajamos {clean_missing} en nuestro catálogo de distribución "
            f"(manejamos líneas de {cat_str.lower()}).\n\n"
            f"💡 Si querés ver todo lo que tenemos disponible para entrega inmediata, "
            f"escribime 'mandame la lista' o consultame por productos puntuales como aceite, harina o bebidas."
        )

    return "\n".join(lines)


async def parse_order_or_inquiry_with_ai(text: str) -> OrderAnalysis:
    """
    Intelligently analyzes customer message with Gemini NLU to understand intent,
    filter out voice stutters/preambles, and extract structured order items or inquiries.
    Falls back to deterministic regex parser if AI is unavailable.
    """
    if not text or not text.strip():
        return OrderAnalysis(intent="other")

    text_clean = text.strip()
    lower_text = text_clean.lower()

    # Fast-path exclusions for admin commands
    if any(lower_text.startswith(w) for w in ["pausar", "activar", "silenciar", "despausar", "resumen", "reporte"]):
        return OrderAnalysis(intent="other")

    # Fast-path for direct price list request
    price_list_triggers = [
        "lista de precio", "lista de precios", "lista actualizada", "pasame la lista", 
        "mandame la lista", "pasanos la lista", "ver la lista", "catalogo", "catálogo", 
        "tienen lista", "tenes lista", "tenés lista", "mandame los precios", "pasame los precios",
        "precios actualizados", "que precios tenes", "qué precios tenés", "el excel", "mandame el excel",
        "pasame el excel", "tu excel", "la planilla", "manda a tabela", "tabela de precos", "tabela de preços",
        "lista completa", "lista de precios completa", "mandame la lista completa", "pasame la lista completa",
        "catalogo completo", "catálogo completo", "el catalogo", "el catálogo", "la lista", "lista entera",
        "todos los precios", "enviame la lista", "enviar la lista", "pasar la lista", "mandame el catalogo",
        "pasame el catalogo", "mandame el catálogo", "pasame el catálogo"
    ]
    if any(k in lower_text for k in price_list_triggers) and not any(k in lower_text for k in ["caja", "fardo", "pack", "anotame", "mandame 2", "mandame 1", "sumame"]):
        return OrderAnalysis(intent="price_list_request")

    possible_triggers = [
        "caja", "cajas", "fardo", "fardos", "pack", "packs", "bolsa", "bolsas",
        "aceite", "harina", "arroz", "fideo", "fideos", "yerba", "leche", "queso",
        "coca", "quilmes", "cajon", "cajones", "cajón", "precio", "precios", "cuanto",
        "cuánto", "stock", "tenes", "tenés", "tienen", "trabajan", "economico", "económico",
        "anotame", "mandame", "traeme", "pasame", "cargame", "sumame", "pedir", "pedido"
    ]
    has_triggers = any(t in lower_text for t in possible_triggers)
    if not has_triggers and not lower_text.startswith("ml"):
        return OrderAnalysis(intent="other")

    gemini_key = settings.GEMINI_API_KEY
    if gemini_key:
        prompt = (
            "Sos el módulo de inteligencia lingüística de Sofía, asistente comercial de una distribuidora mayorista en Argentina.\n"
            "Analizá el mensaje del cliente (que puede venir de una nota de voz con trabas de audio, inicios cortados como 'ml...', 'para para', tartamudeos o lenguaje coloquial argentino).\n\n"
            "Tu tarea es clasificar la intención y extraer los datos estructurados:\n"
            "1. 'intent':\n"
            "   - 'order': El cliente quiere encargar, pedir o sumar productos específicos con intención de compra (ej: 'anotame 2 cajas de aceite', 'mandame fardos de harina').\n"
            "   - 'product_inquiry': El cliente pregunta por disponibilidad, precio o variedad de productos (ej: '¿tenés fideos?', 'fideo del más económico que tengas', 'a cuánto está el aceite?').\n"
            "   - 'price_list_request': El cliente pide el catálogo o la lista completa de precios (ej: 'pasame la lista', 'mandame el excel').\n"
            "   - 'other': Saludo, agradecimiento o charla general sin productos.\n\n"
            "2. 'items': Lista de productos y cantidades SOLO si intent es 'order':\n"
            "   - 'product_name': nombre limpio del producto (ej: 'aceite cañuelas', 'harina').\n"
            "   - 'quantity': número entero.\n"
            "   - 'unit_type': 'caja', 'fardo', 'pack', 'unidad', etc.\n\n"
            "3. 'inquired_products': Lista de nombres limpios de productos si es 'product_inquiry' (ej: ['fideo económico']).\n\n"
            "4. 'cleaned_meaning': Breve resumen de lo que quiso decir el cliente, descartando muletillas y trabas del audio (como 'ml', 'para para pedirte').\n\n"
            "Respondé ÚNICAMENTE un JSON válido con estas 4 claves: 'intent', 'items', 'inquired_products', 'cleaned_meaning'.\n\n"
            f"Mensaje del cliente:\n\"{text_clean}\""
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={gemini_key}"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.post(
                    url,
                    json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"response_mime_type": "application/json"}}
                )
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts:
                            raw_json = parts[0].get("text", "")
                            parsed = json.loads(raw_json)
                            intent = parsed.get("intent", "other")
                            inquired = parsed.get("inquired_products") or []
                            items = parsed.get("items") or []
                            meaning = parsed.get("cleaned_meaning")

                            if intent == "order" and items:
                                draft = build_order_draft_from_entities(items)
                                return OrderAnalysis(
                                    intent="order",
                                    draft=draft,
                                    cleaned_meaning=meaning
                                )
                            elif intent == "product_inquiry" or (not items and inquired):
                                clean_inquired = [q for q in inquired if not is_conversational_filler(q)]
                                if clean_inquired:
                                    return OrderAnalysis(
                                        intent="product_inquiry",
                                        inquired_products=clean_inquired,
                                        cleaned_meaning=meaning
                                    )
                            elif intent == "price_list_request":
                                return OrderAnalysis(
                                    intent="price_list_request",
                                    cleaned_meaning=meaning
                                )
                            elif intent == "order" and not items:
                                pass
                            else:
                                return OrderAnalysis(intent="other", cleaned_meaning=meaning)
        except Exception as e:
            logger.warning(f"Error in parse_order_or_inquiry_with_ai via Gemini: {e}")

    # Fallback to improved regex parser
    draft = parse_order_text(text_clean)
    if draft.items:
        if detect_order_intent(text_clean) or any(w in lower_text for w in ["caja", "cajas", "fardo", "fardos", "pack", "packs", "anotame", "mandame", "traeme", "cargame"]):
            return OrderAnalysis(intent="order", draft=draft)
        else:
            return OrderAnalysis(intent="product_inquiry", inquired_products=[it.product.name for it in draft.items])
    elif draft.unmatched_queries:
        clean_unmatched = [q for q in draft.unmatched_queries if not is_conversational_filler(q)]
        draft.unmatched_queries = clean_unmatched
        if clean_unmatched:
            if detect_order_intent(text_clean) or any(w in lower_text for w in ["caja", "cajas", "fardo", "fardos", "pack", "packs", "anotame", "mandame", "traeme", "cargame"]):
                return OrderAnalysis(intent="order", draft=draft)
            else:
                return OrderAnalysis(intent="product_inquiry", inquired_products=clean_unmatched)

    return OrderAnalysis(intent="other")

