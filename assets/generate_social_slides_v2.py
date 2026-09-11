import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"

def get_fonts():
    return {
        "tag": ImageFont.truetype(FONT_BOLD, 26),
        "pill": ImageFont.truetype(FONT_BOLD, 22),
        "title_xl": ImageFont.truetype(FONT_BOLD, 56),
        "title": ImageFont.truetype(FONT_BOLD, 44),
        "card_title": ImageFont.truetype(FONT_BOLD, 32),
        "subtitle": ImageFont.truetype(FONT_REGULAR, 29),
        "body_bold": ImageFont.truetype(FONT_BOLD, 26),
        "body": ImageFont.truetype(FONT_REGULAR, 25),
        "caption": ImageFont.truetype(FONT_REGULAR, 22),
        "cta_big": ImageFont.truetype(FONT_BOLD, 74),
        "price_big": ImageFont.truetype(FONT_BOLD, 68),
    }

def create_base_canvas():
    w, h = 1080, 1920
    img = Image.new("RGBA", (w, h), (11, 16, 27, 255))
    draw = ImageDraw.Draw(img)
    
    # Smooth vertical gradient
    for y in range(h):
        ratio = y / h
        r = int(11 + (16 - 11) * ratio)
        g = int(16 + (24 - 16) * ratio)
        b = int(27 + (40 - 27) * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b, 255))
    
    # Ambient glows
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse([650, 120, 1150, 620], fill=(37, 211, 102, 35))
    glow_draw.ellipse([-200, 1150, 420, 1750], fill=(56, 189, 248, 30))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.alpha_composite(img, glow)
    return img

def draw_story_bars(draw, active_index, total=8):
    bar_w = int((1080 - 120 - (total - 1) * 12) / total)
    bar_h = 8
    start_x = 60
    y = 55
    for i in range(total):
        x = start_x + i * (bar_w + 12)
        if i == active_index:
            color = (37, 211, 102, 255)
        elif i < active_index:
            color = (255, 255, 255, 210)
        else:
            color = (255, 255, 255, 60)
        draw.rounded_rectangle([x, y, x + bar_w, y + bar_h], radius=4, fill=color)

def draw_header_badge(draw, text, y=95, color=(37, 211, 102)):
    fonts = get_fonts()
    bbox = fonts["tag"].getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    px, py = 26, 12
    w = tw + px * 2
    h = th + py * 2
    x = (1080 - w) // 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h//2, fill=(20, 32, 48, 245), outline=color, width=2)
    draw.text((x + px, y + py - 2), text, fill=color, font=fonts["tag"])

def draw_pill(draw, text, x, y, bg=(37, 211, 102, 40), border=(37, 211, 102, 220), text_color=(37, 211, 102)):
    fonts = get_fonts()
    bbox = fonts["pill"].getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    px, py = 16, 6
    w = tw + px * 2
    h = th + py * 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=bg, outline=border, width=1)
    draw.text((x + px, y + py - 2), text, fill=text_color, font=fonts["pill"])
    return w

def get_circular_avatar(size=260):
    avatar_path = "assets/sofia_avatar.jpg"
    if not os.path.exists(avatar_path):
        return None
    av = Image.open(avatar_path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    m_draw = ImageDraw.Draw(mask)
    m_draw.ellipse([0, 0, size, size], fill=255)
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(av, (0, 0), mask)
    
    bordered = Image.new("RGBA", (size + 16, size + 16), (0, 0, 0, 0))
    b_draw = ImageDraw.Draw(bordered)
    b_draw.ellipse([0, 0, size + 15, size + 15], outline=(37, 211, 102, 255), width=6)
    bordered.paste(output, (8, 8), output)
    return bordered

# ==============================================================================
# SLIDE 1: PORTADA IMPACTO / PRESENTACIÓN
# ==============================================================================
def build_slide_1():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 0, total=8)
    draw_header_badge(draw, "SOFÍA 2.0 • ASISTENTE PARA COMERCIOS")
    fonts = get_fonts()
    
    av = get_circular_avatar(size=270)
    if av:
        img.paste(av, ((1080 - av.width) // 2, 200), av)
        draw = ImageDraw.Draw(img)
    
    # Online badge
    draw.rounded_rectangle([425, 495, 655, 545], radius=24, fill=(15, 23, 42, 250), outline=(37, 211, 102, 255), width=2)
    draw.ellipse([445, 513, 459, 527], fill=(37, 211, 102, 255))
    draw.text((475, 507), "EN TU WHATSAPP 24/7", fill=(255, 255, 255), font=fonts["caption"])

    draw.text((540, 620), "Tu Asistente Comercial\nen WhatsApp", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    
    sub = "Atiende a tus clientes, actualiza tus precios por Excel\ny le pasa los pedidos a tus proveedores con remito en PDF."
    draw.text((540, 735), sub, fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm", align="center")
    
    draw.rounded_rectangle([80, 835, 1000, 1620], radius=30, fill=(17, 24, 39, 235), outline=(51, 65, 85, 190), width=2)
    
    items = [
        ("AUDIOS", "Entiende notas de voz y cotiza", "Toma pedidos complejos de clientes y calcula el total exacto en segundos.", (37, 211, 102)),
        ("EXCEL", "Actualiza precios de proveedores", "Le mandás la planilla nueva y actualiza todo tu catálogo en 5 segundos.", (56, 189, 248)),
        ("PROVEEDORES", "Canastas y remitos automáticos", "Le anota los pedidos a cada distribuidor y les despacha el remito en PDF.", (250, 204, 21)),
        ("MODO DUEÑO", "Control total por notas de voz", "Hablale como a tu socia de confianza para ver ventas, stock y directivas.", (168, 85, 247))
    ]
    
    y = 875
    for tag, title, desc, accent in items:
        pw = draw_pill(draw, tag, 115, y, bg=(accent[0], accent[1], accent[2], 30), border=accent, text_color=accent)
        draw.text((115 + pw + 18, y + 2), title, fill=(255, 255, 255), font=fonts["card_title"])
        draw.text((115, y + 55), desc, fill=(203, 213, 225), font=fonts["body"])
        y += 180

    draw.text((540, 1745), "Deslizá para ver cómo vende por vos »", fill=(37, 211, 102), font=fonts["subtitle"], anchor="mm")
    return img

# ==============================================================================
# SLIDE 2: EL DOLOR DIARIO DEL COMERCIANTE
# ==============================================================================
def build_slide_2():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 1, total=8)
    draw_header_badge(draw, "EL DOLOR DE TODO NEGOCIO", color=(248, 113, 113))
    fonts = get_fonts()
    
    draw.text((540, 210), "¿Cansado de perder horas\ncon precios y pedidos?", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "Los 3 problemas diarios de ferreterías, almacenes y comercios:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")
    
    problems = [
        ("1", "Precios desactualizados", "El proveedor manda aumentos todas las semanas.\nSi no actualizás a tiempo, perdés plata vendiendo barato."),
        ("2", "Audios eternos de clientes", "Mensajes de voz pidiendo precios a las 22 hs o feriados.\nResponder a mano cansa y si demorás, compran en otro lado."),
        ("3", "Pedidos en papelitos rotos", "Anotás faltantes en hojas sueltas, te olvidás de pedirle\nal mayorista y te quedás sin mercadería en el mostrador.")
    ]
    
    y = 405
    for num, title, desc in problems:
        draw.rounded_rectangle([80, y, 1000, y + 265], radius=26, fill=(24, 18, 26, 230), outline=(239, 68, 68, 160), width=2)
        pw = draw_pill(draw, f"PROBLEMA {num}", 120, y + 26, bg=(239, 68, 68, 40), border=(239, 68, 68, 200), text_color=(252, 165, 165))
        draw.text((120, y + 78), title, fill=(252, 165, 165), font=fonts["card_title"])
        draw.text((120, y + 138), desc, fill=(226, 232, 240), font=fonts["body"])
        y += 290

    draw.rounded_rectangle([80, 1315, 1000, 1615], radius=26, fill=(15, 34, 25, 245), outline=(37, 211, 102, 220), width=2)
    draw.text((540, 1385), "La Solución con Sofía:", fill=(37, 211, 102), font=fonts["title"], anchor="mm")
    draw.text((540, 1485), "Automatizá todo directo en tu WhatsApp.\nSin computadoras especiales ni programas raros.", fill=(255, 255, 255), font=fonts["subtitle"], anchor="mm", align="center")

    draw.text((540, 1750), "Mirá cómo actualiza precios en vivo »", fill=(148, 163, 184), font=fonts["body_bold"], anchor="mm")
    return img

# ==============================================================================
# SLIDE 3: ACTUALIZACIÓN MÁGICA DE PRECIOS CON EXCEL
# ==============================================================================
def build_slide_3():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 2, total=8)
    draw_header_badge(draw, "CHAU HORAS DE EXCEL MANUAL", color=(52, 211, 153))
    fonts = get_fonts()
    
    draw.text((540, 210), "¿Aumentó el proveedor?\nSofía lo actualiza en 5 seg", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "Olvidate de cambiar precios uno por uno a mano:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")
    
    cards = [
        ("PASO 1", "Le mandás el Excel o foto por WhatsApp", "Tu catálogo actual + la lista nueva que te envió la fábrica,\ndistribuidora o mayorista con los aumentos."),
        ("PASO 2", "Emparejamiento inteligente de artículos", "Sofía cruza los productos aunque los nombres no coincidan exacto\n(ej: «Martillo galponero» con «Martillo fibra 500g»)."),
        ("PASO 3", "Precios en vivo y Excel recalculado", "Sofía empieza a cotizar con precios nuevos al segundo\ny te devuelve la planilla final lista para consultar o imprimir.")
    ]
    
    y = 405
    for tag, title, desc in cards:
        draw.rounded_rectangle([80, y, 1000, y + 265], radius=26, fill=(17, 24, 39, 230), outline=(52, 211, 153, 160), width=2)
        pw = draw_pill(draw, tag, 120, y + 26, bg=(52, 211, 153, 35), border=(52, 211, 153, 200), text_color=(52, 211, 153))
        draw.text((120, y + 78), title, fill=(255, 255, 255), font=fonts["card_title"])
        draw.text((120, y + 138), desc, fill=(226, 232, 240), font=fonts["body"])
        y += 290

    draw.rounded_rectangle([80, 1315, 1000, 1615], radius=26, fill=(15, 34, 25, 240), outline=(37, 211, 102, 220), width=2)
    draw.text((540, 1385), "Chau fórmulas y planillas rotas", fill=(37, 211, 102), font=fonts["title"], anchor="mm")
    draw.text((540, 1485), "Sin BUSCARV, sin errores humanos y sin perder\nmárgenes de ganancia. Tu mostrador siempre al día.", fill=(255, 255, 255), font=fonts["subtitle"], anchor="mm", align="center")

    draw.text((540, 1750), "Mirá cómo toma pedidos por audio »", fill=(37, 211, 102), font=fonts["body_bold"], anchor="mm")
    return img

# ==============================================================================
# SLIDE 4: ENTIENDE AUDIOS Y COTIZA AL INSTANTE
# ==============================================================================
def build_slide_4():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 3, total=8)
    draw_header_badge(draw, "ATENCIÓN AL CLIENTE 24/7", color=(56, 189, 248))
    fonts = get_fonts()
    
    draw.text((540, 210), "Tus clientes le mandan audio\ny Sofía vende al instante", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "No perdés una venta más de noche, domingos ni feriados:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")

    steps = [
        ("CLIENTE (AUDIO)", "«Hola, mandame 4 martillos y 2 alicates»", "El cliente manda un audio informal por WhatsApp.", (255, 255, 255)),
        ("SOFÍA (2 SEG)", "Calcula con matemática exacta y stock:", "• 4x Martillos: $58.000  |  2x Alicates: $22.000\nTOTAL: $80.000. ¿Te lo confirmo para armar?", (37, 211, 102)),
        ("CLIENTE", "«Sí, dale, confirmalo»", "Sofía ingresa el pedido automáticamente en la base de datos.", (56, 189, 248)),
        ("DESPACHO", "Aviso en vivo a tu celular o depósito:", "Llega el remito listo para preparar el paquete\ny salir a reparto sin demoras ni confusiones.", (250, 204, 21))
    ]

    y = 405
    for tag, step_title, step_desc, accent in steps:
        h = 245 if "\n" in step_desc else 185
        draw.rounded_rectangle([80, y, 1000, y + h], radius=24, fill=(15, 23, 42, 240), outline=(51, 65, 85, 200), width=2)
        pw = draw_pill(draw, tag, 110, y + 22, bg=(30, 41, 59, 220), border=accent, text_color=accent)
        draw.text((110 + pw + 16, y + 24), step_title, fill=(255, 255, 255), font=fonts["card_title"])
        draw.text((110, y + 78), step_desc, fill=accent if tag.startswith("SOFÍA") else (226, 232, 240), font=fonts["body"])
        y += h + 20

    draw.rounded_rectangle([80, 1370, 1000, 1630], radius=26, fill=(20, 33, 25, 240), outline=(37, 211, 102, 200), width=2)
    draw.text((540, 1450), "«Atiende con calidez, rapidez", fill=(37, 211, 102), font=fonts["title"], anchor="mm")
    draw.text((540, 1530), "y matemática 100% exacta»", fill=(255, 255, 255), font=fonts["title"], anchor="mm")

    draw.text((540, 1750), "Mirá cómo maneja 20 proveedores a la vez »", fill=(148, 163, 184), font=fonts["body_bold"], anchor="mm")
    return img

# ==============================================================================
# SLIDE 5: ¿TENÉS 20 PROVEEDORES? MANEJALOS EN UN SOLO LUGAR (¡EL EFECTO WOW!)
# ==============================================================================
def build_slide_proveedores_hub():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 4, total=8)
    draw_header_badge(draw, "EL HUB DE TUS PROVEEDORES • CERO PAPELES", color=(251, 146, 60))
    fonts = get_fonts()
    
    draw.text((540, 210), "¿Tenés 20 proveedores?\nManejá todo en un solo chat", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "Una canasta inteligente en WhatsApp para cada distribuidora:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")

    baskets = [
        ("BULONERA LITORAL", "«Sofi, anotá 4 cajas de tornillos y 2 pinzas»", "📦 Acumulado: 6 artículos listos para pedir.", (56, 189, 248)),
        ("DISTRIBUIDORA QUILMES", "«Sofi, sumá 10 cajones y 5 packs de agua»", "📦 Acumulado: 15 bultos para el próximo camión.", (250, 204, 21)),
        ("PINTURAS LITORAL", "«Sofi, agregá 3 baldes de látex blanco 20L»", "📦 Acumulado: 3 artículos en espera.", (168, 85, 247))
    ]

    y = 405
    for tag, voice_cmd, desc, accent in baskets:
        draw.rounded_rectangle([80, y, 1000, y + 265], radius=26, fill=(17, 24, 39, 235), outline=(accent[0], accent[1], accent[2], 160), width=2)
        pw = draw_pill(draw, tag, 115, y + 24, bg=(accent[0], accent[1], accent[2], 30), border=accent, text_color=accent)
        draw.text((115, y + 80), voice_cmd, fill=(255, 255, 255), font=fonts["card_title"])
        draw.text((115, y + 142), desc, fill=(226, 232, 240), font=fonts["body"])
        draw.text((115, y + 198), "💡 Guardado automáticamente por nota de voz", fill=accent, font=fonts["caption"])
        y += 290

    draw.rounded_rectangle([80, 1315, 1000, 1615], radius=26, fill=(15, 34, 25, 245), outline=(37, 211, 102, 220), width=2)
    draw.text((540, 1385), "Antes de que pase el preventista:", fill=(37, 211, 102), font=fonts["title"], anchor="mm")
    draw.text((540, 1485), "Le decís: «Sofi, ¿qué tenemos para pedirle a la Bulonera?»\ny te canta la lista completa en segundos. Cero olvidos.", fill=(255, 255, 255), font=fonts["subtitle"], anchor="mm", align="center")

    draw.text((540, 1750), "Mirá cómo despacha los remitos en PDF »", fill=(37, 211, 102), font=fonts["body_bold"], anchor="mm")
    return img

# ==============================================================================
# SLIDE 6: DESPACHO CON REMITO EN PDF AL MAYORISTA
# ==============================================================================
def build_slide_despacho_remito():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 5, total=8)
    draw_header_badge(draw, "ORDEN FORMAL CON REMITO PDF", color=(250, 204, 21))
    fonts = get_fonts()
    
    draw.text((540, 210), "Despachale al mayorista\ncon una sola frase", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "El proveedor recibe una orden de compra profesional:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")

    cards = [
        ("1. LA ORDEN", "Le hablás a Sofía por WhatsApp:", "«Sofi, mandale el pedido formal a Distribuidora Alem».\nNo tenés que redactar nada ni buscar el número.", (255, 255, 255)),
        ("2. EL REMITO", "Genera el Remito membretado en PDF:", "Con el nombre de tu comercio, logo, detalle de bultos,\ncantidades exactas y fecha de entrega solicitada.", (56, 189, 248)),
        ("3. EL ENVÍO", "Llega al WhatsApp del mayorista en vivo:", "Sofía se lo envía por WhatsApp al encargado del mayorista\ncon la plantilla oficial y el PDF adjunto al instante.", (37, 211, 102))
    ]

    y = 405
    for tag, title, desc, accent in cards:
        draw.rounded_rectangle([80, y, 1000, y + 265], radius=26, fill=(17, 24, 39, 230), outline=(250, 204, 21, 150), width=2)
        pw = draw_pill(draw, tag, 120, y + 26, bg=(250, 204, 21, 30), border=(250, 204, 21, 200), text_color=(250, 204, 21))
        draw.text((120, y + 78), title, fill=(255, 255, 255), font=fonts["card_title"])
        draw.text((120, y + 138), desc, fill=(226, 232, 240), font=fonts["body"])
        y += 290

    draw.rounded_rectangle([80, 1315, 1000, 1615], radius=26, fill=(15, 23, 42, 240), outline=(37, 211, 102, 200), width=2)
    draw.text((540, 1385), "Tu negocio gana estatus y prioridad", fill=(37, 211, 102), font=fonts["title"], anchor="mm")
    draw.text((540, 1485), "Tu mayorista recibe un pedido prolijo e impecable.\nTe preparan el pedido antes y no hay confusiones.", fill=(255, 255, 255), font=fonts["subtitle"], anchor="mm", align="center")

    draw.text((540, 1750), "Mirá el Modo Dueño »", fill=(37, 211, 102), font=fonts["body_bold"], anchor="mm")
    return img

# ==============================================================================
# SLIDE 7: MODO DUEÑO: CONTROL TOTAL POR WHATSAPP
# ==============================================================================
def build_slide_modo_dueno():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 6, total=8)
    draw_header_badge(draw, "MODO DUEÑO • CONTROL TOTAL", color=(168, 85, 247))
    fonts = get_fonts()
    
    draw.text((540, 210), "Manejá tu negocio hablándole\npor nota de voz", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "Como tener a tu socia o encargada de máxima confianza en el celular:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")

    cards = [
        ("🎙️ VENTAS Y MÉTRICAS", "«Sofi, ¿cómo venimos hoy?»", "Te canta el resumen de pedidos tomados, clientes atendidos\ny total facturado en el día en segundos."),
        ("🎙️ DIRECTIVAS EN VIVO", "«Sofi, flete gratis desde $50.000»", "Le pasás tus reglas de reparto, horarios de corte o zonas\ny las aplica de inmediato con los clientes."),
        ("🎙️ PRECIOS Y STOCK", "«Sofi, subí el martillo a $17.400»", "Modificá artículos individuales por audio y queda actualizado\nen todo tu catálogo sin tocar la computadora.")
    ]

    y = 405
    for tag, title, desc in cards:
        draw.rounded_rectangle([80, y, 1000, y + 265], radius=26, fill=(17, 24, 39, 230), outline=(168, 85, 247, 160), width=2)
        pw = draw_pill(draw, tag, 120, y + 26, bg=(168, 85, 247, 30), border=(168, 85, 247, 200), text_color=(216, 180, 254))
        draw.text((120, y + 78), title, fill=(255, 255, 255), font=fonts["card_title"])
        draw.text((120, y + 138), desc, fill=(226, 232, 240), font=fonts["body"])
        y += 290

    draw.rounded_rectangle([80, 1315, 1000, 1615], radius=26, fill=(15, 23, 42, 240), outline=(51, 65, 85, 220), width=2)
    draw.text((540, 1385), "Cero apps nuevas • Cero contraseñas", fill=(255, 255, 255), font=fonts["title"], anchor="mm")
    draw.text((540, 1485), "No tenés que sentarte en la compu ni aprender nada nuevo.\nTodo funciona en el WhatsApp que ya usás todos los días.", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm", align="center")

    draw.text((540, 1750), "Deslizá para probarla gratis en tu negocio »", fill=(37, 211, 102), font=fonts["body_bold"], anchor="mm")
    return img

# ==============================================================================
# SLIDE 8: OFERTA IRRESISTIBLE & CIERRE (CTA)
# ==============================================================================
def build_slide_cta():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 7, total=8)
    draw_header_badge(draw, "LANZAMIENTO EXCLUSIVO COMERCIOS", color=(37, 211, 102))
    fonts = get_fonts()
    
    av = get_circular_avatar(size=210)
    if av:
        img.paste(av, ((1080 - av.width) // 2, 185), av)
        draw = ImageDraw.Draw(img)

    draw.text((540, 445), "Sumá a Sofía a tu negocio\nhoy mismo", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 530), "Atención 24/7, precios al día y pedidos a proveedores:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")

    # Pricing & Value Card
    draw.rounded_rectangle([80, 580, 1000, 1180], radius=32, fill=(15, 34, 25, 250), outline=(37, 211, 102, 255), width=3)
    
    draw.text((540, 640), "PLAN COMERCIO CHICO", fill=(148, 163, 184), font=fonts["body_bold"], anchor="mm")
    draw.text((540, 720), "$35.000 ARS / mes", fill=(37, 211, 102), font=fonts["price_big"], anchor="mm")
    draw.text((540, 790), "(Menos de lo que vale una pizza por mes)", fill=(203, 213, 225), font=fonts["body"], anchor="mm")
    
    draw.line([(150, 835), (930, 835)], fill=(37, 211, 102, 100), width=1)
    
    # Guarantee section
    draw.rounded_rectangle([120, 865, 960, 930], radius=16, fill=(37, 211, 102, 35), outline=(37, 211, 102, 200), width=1)
    draw.text((540, 898), "🛡️ GARANTÍA TOTAL: 7 DÍAS DE PRUEBA SIN RIESGO", fill=(37, 211, 102), font=fonts["body_bold"], anchor="mm")
    
    gt_text = "La configuramos en tu WhatsApp con tus productos y la probás\nuna semana entera. Si no te ahorra horas de trabajo, no pagás nada."
    draw.text((540, 1010), gt_text, fill=(226, 232, 240), font=fonts["body"], anchor="mm", align="center")
    
    draw.text((540, 1115), "✅ Sin contratos largos • Cancelás cuando quieras", fill=(250, 204, 21), font=fonts["caption"], anchor="mm")

    # CTA Action Box
    draw.rounded_rectangle([80, 1220, 1000, 1630], radius=28, fill=(15, 23, 42, 240), outline=(56, 189, 248, 200), width=2)
    draw.text((540, 1285), "Respondé a este estado o historia con:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")
    draw.text((540, 1375), "«QUIERO A SOFÍA»", fill=(37, 211, 102), font=fonts["cta_big"], anchor="mm")
    draw.text((540, 1465), "O escribinos directo al WhatsApp:", fill=(203, 213, 225), font=fonts["body"], anchor="mm")
    draw.text((540, 1535), "+54 9 343 572-0312", fill=(56, 189, 248), font=fonts["title"], anchor="mm")

    draw.text((540, 1750), "🚀 Cupos limitados para comercios de Entre Ríos y Santa Fe", fill=(250, 204, 21), font=fonts["caption"], anchor="mm")
    return img

def main():
    target_dir = "assets/slides_v2"
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs("assets/slides", exist_ok=True)
    
    builders = [
        ("slide_1_portada.png", build_slide_1),
        ("slide_2_problema.png", build_slide_2),
        ("slide_3_actualizacion_precios.png", build_slide_3),
        ("slide_4_pedidos_audio.png", build_slide_4),
        ("slide_5_hub_20_proveedores.png", build_slide_proveedores_hub),
        ("slide_6_pedidos_proveedores.png", build_slide_despacho_remito),
        ("slide_7_modo_dueno.png", build_slide_modo_dueno),
        ("slide_8_cta_oferta.png", build_slide_cta),
    ]
    
    for filename, builder in builders:
        slide = builder()
        path_v2 = os.path.join(target_dir, filename)
        path_v1 = os.path.join("assets/slides", filename)
        slide.save(path_v2, "PNG", optimize=True)
        slide.save(path_v1, "PNG", optimize=True)
        print(f"✅ Generated: {path_v2} and {path_v1}")

if __name__ == "__main__":
    main()
