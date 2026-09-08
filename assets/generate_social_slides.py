import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"

def get_fonts():
    return {
        "tag": ImageFont.truetype(FONT_BOLD, 26),
        "pill": ImageFont.truetype(FONT_BOLD, 22),
        "title_xl": ImageFont.truetype(FONT_BOLD, 66),
        "title": ImageFont.truetype(FONT_BOLD, 46),
        "card_title": ImageFont.truetype(FONT_BOLD, 36),
        "subtitle": ImageFont.truetype(FONT_REGULAR, 34),
        "body_bold": ImageFont.truetype(FONT_BOLD, 30),
        "body": ImageFont.truetype(FONT_REGULAR, 28),
        "caption": ImageFont.truetype(FONT_REGULAR, 24),
        "cta_big": ImageFont.truetype(FONT_BOLD, 84),
    }

def create_base_canvas():
    w, h = 1080, 1920
    img = Image.new("RGBA", (w, h), (11, 16, 27, 255))
    draw = ImageDraw.Draw(img)
    
    for y in range(h):
        ratio = y / h
        r = int(11 + (17 - 11) * ratio)
        g = int(16 + (24 - 16) * ratio)
        b = int(27 + (39 - 27) * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b, 255))
    
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse([650, 150, 1150, 650], fill=(37, 211, 102, 30))
    glow_draw.ellipse([-200, 1200, 400, 1800], fill=(56, 189, 248, 24))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.alpha_composite(img, glow)
    return img

def draw_story_bars(draw, active_index, total=6):
    bar_w = int((1080 - 120 - (total - 1) * 14) / total)
    bar_h = 8
    start_x = 60
    y = 55
    for i in range(total):
        x = start_x + i * (bar_w + 14)
        if i == active_index:
            color = (37, 211, 102, 255)
        elif i < active_index:
            color = (255, 255, 255, 200)
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
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h//2, fill=(20, 32, 48, 240), outline=color, width=2)
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

# ----------------- SLIDES -----------------

def build_slide_1():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 0)
    draw_header_badge(draw, "SOFÍA • AGENCIA DE IA")
    fonts = get_fonts()
    
    av = get_circular_avatar(size=280)
    if av:
        img.paste(av, ((1080 - av.width) // 2, 210), av)
        draw = ImageDraw.Draw(img)
    
    draw.rounded_rectangle([440, 520, 640, 568], radius=24, fill=(15, 23, 42, 250), outline=(37, 211, 102, 255), width=2)
    draw.ellipse([460, 538, 474, 552], fill=(37, 211, 102, 255))
    draw.text((490, 532), "ONLINE 24/7", fill=(255, 255, 255), font=fonts["caption"])

    draw.text((540, 645), "Conocé a Sofía", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm")
    
    sub = "La ejecutiva comercial con IA que atiende,\ncotiza y vende en tu WhatsApp\ncon la marca y precios de tu negocio."
    draw.text((540, 770), sub, fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm", align="center")
    
    draw.rounded_rectangle([80, 890, 1000, 1630], radius=32, fill=(17, 24, 39, 230), outline=(51, 65, 85, 180), width=2)
    
    items = [
        ("MAPS", "Sale a buscar clientes a diario", "Escribe a 12-15 comercios de tu zona por día."),
        ("EXCEL", "Carga tus listas de precios", "Actualiza precios y promociones al instante."),
        ("AUDIO", "Entiende notas de voz", "Toma pedidos complejos y calcula el total exacto."),
        ("DEPÓSITO", "Envía la orden lista para armar", "Con remito armado para despachar sin demoras.")
    ]
    
    y = 940
    for tag, title, desc in items:
        pw = draw_pill(draw, tag, 120, y)
        draw.text((120 + pw + 18, y + 2), title, fill=(255, 255, 255), font=fonts["body_bold"])
        draw.text((120, y + 55), desc, fill=(148, 163, 184), font=fonts["body"])
        y += 165

    draw.text((540, 1750), "Deslizá para ver cómo funciona »", fill=(37, 211, 102), font=fonts["subtitle"], anchor="mm")
    return img

def build_slide_2():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 1)
    draw_header_badge(draw, "EL DOLOR DE TODO NEGOCIO", color=(248, 113, 113))
    fonts = get_fonts()
    
    draw.text((540, 210), "¿Cansado de perder ventas\nfuera de horario?", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "Los 3 problemas diarios de distribuidoras y pymes:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")
    
    problems = [
        ("1", "Consultas sin responder de noche", "Tus clientes piden listas a las 21 hs o domingos.\nSi nadie responde rápido, le compran a otro."),
        ("2", "Horas pasando precios a mano", "Tus empleados o vos tiroteados respondiendo lo\nmismo 50 veces al día en vez de salir a vender."),
        ("3", "Pedidos trabados o mal calculados", "Notas de voz eternas, cuentas mal hechas en papel\ny demoras para pasarle la orden al depósito.")
    ]
    
    y = 405
    for num, title, desc in problems:
        draw.rounded_rectangle([80, y, 1000, y + 260], radius=26, fill=(24, 18, 26, 220), outline=(239, 68, 68, 160), width=2)
        pw = draw_pill(draw, f"PROBLEMA {num}", 120, y + 26, bg=(239, 68, 68, 40), border=(239, 68, 68, 200), text_color=(252, 165, 165))
        draw.text((120, y + 78), title, fill=(252, 165, 165), font=fonts["card_title"])
        draw.text((120, y + 138), desc, fill=(203, 213, 225), font=fonts["body"])
        y += 285

    draw.rounded_rectangle([80, 1315, 1000, 1615], radius=26, fill=(15, 34, 25, 240), outline=(37, 211, 102, 200), width=2)
    draw.text((540, 1385), "La Solución con Sofía:", fill=(37, 211, 102), font=fonts["title"], anchor="mm")
    draw.text((540, 1485), "Atención inmediata 24/7, cuentas exactas\ny los pedidos listos para armar en 1 segundo.", fill=(255, 255, 255), font=fonts["subtitle"], anchor="mm", align="center")

    draw.text((540, 1750), "Mirá cómo el dueño controla todo »", fill=(148, 163, 184), font=fonts["body_bold"], anchor="mm")
    return img

def build_slide_3():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 2)
    draw_header_badge(draw, "CERO PROGRAMAS COMPLICADOS", color=(56, 189, 248))
    fonts = get_fonts()
    
    draw.text((540, 210), "Todo el control desde tu\npropio WhatsApp", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "Sin contraseñas, sin instalar nada, sin capacitar gente.", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")
    
    cards = [
        ("EXCEL", "1. Le mandás tu lista de precios", "Sofía procesa tu archivo en segundos, lee todos los\nproductos y cotiza siempre con tus precios al día."),
        ("AUDIO", "2. Le das directivas por nota de voz", "«Sofi, mínimo $50.000 para flete gratis y repartimos\nsolo en zona centro». Lo aprende y lo aplica ya."),
        ("MÉTRICAS", "3. Le pedís métricas cuando quieras", "Escribís «resumen» y te canta cuántos pedidos entraron,\ncuántos clientes hablaron y el estado de la línea.")
    ]
    
    y = 405
    for tag, title, desc in cards:
        draw.rounded_rectangle([80, y, 1000, y + 260], radius=26, fill=(17, 24, 39, 230), outline=(56, 189, 248, 160), width=2)
        pw = draw_pill(draw, tag, 120, y + 26, bg=(56, 189, 248, 40), border=(56, 189, 248, 200), text_color=(56, 189, 248))
        draw.text((120, y + 78), title, fill=(255, 255, 255), font=fonts["card_title"])
        draw.text((120, y + 138), desc, fill=(226, 232, 240), font=fonts["body"])
        y += 285

    draw.rounded_rectangle([80, 1315, 1000, 1615], radius=26, fill=(15, 23, 42, 240), outline=(51, 65, 85, 220), width=2)
    draw.text((540, 1385), "100% en la palma de tu mano", fill=(255, 255, 255), font=fonts["title"], anchor="mm")
    draw.text((540, 1485), "El dueño maneja la distribuidora chateando con Sofía\ncomo si fuera su asistente de máxima confianza.", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm", align="center")

    draw.text((540, 1750), "Mirá cómo toma un pedido en vivo »", fill=(37, 211, 102), font=fonts["body_bold"], anchor="mm")
    return img

def build_slide_4():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 3)
    draw_header_badge(draw, "OPERATORIA EN VIVO")
    fonts = get_fonts()
    
    draw.text((540, 210), "De la consulta al depósito\nen 1 segundo", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "Mirá el circuito automático paso a paso:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")

    steps = [
        ("PASO 1", "El cliente escribe o manda un audio:", "«Mandame 1 caja de aceite y 2 fardos de harina.»", (255, 255, 255)),
        ("PASO 2", "Sofía calcula con matemática exacta:", "• 1x Aceite Cañuelas: $14.400  |  2x Harina Pureza: $25.000\nTOTAL ESTIMADO: $39.400. ¿Te lo confirmo?", (37, 211, 102)),
        ("PASO 3", "El cliente confirma la orden:", "«Sí, dale». Sofía ingresa el pedido en la base de datos.", (56, 189, 248)),
        ("PASO 4", "Alerta instantánea al depósito / dueño:", "Llega el WhatsApp al depósito con los bultos para armar\ny los datos del cliente para despachar.", (250, 204, 21))
    ]

    y = 405
    for tag, step_title, step_desc, accent in steps:
        h = 245 if "\n" in step_desc else 185
        draw.rounded_rectangle([80, y, 1000, y + h], radius=24, fill=(15, 23, 42, 240), outline=(51, 65, 85, 200), width=2)
        pw = draw_pill(draw, tag, 110, y + 22, bg=(30, 41, 59, 220), border=accent, text_color=accent)
        draw.text((110 + pw + 16, y + 24), step_title, fill=(255, 255, 255), font=fonts["body_bold"])
        draw.text((110, y + 78), step_desc, fill=accent if tag == "PASO 2" else (226, 232, 240), font=fonts["body"])
        y += h + 20

    draw.rounded_rectangle([80, 1370, 1000, 1630], radius=26, fill=(20, 33, 25, 240), outline=(37, 211, 102, 200), width=2)
    draw.text((540, 1450), "«Hago el trabajo aburrido", fill=(37, 211, 102), font=fonts["title"], anchor="mm")
    draw.text((540, 1530), "que nadie quiere hacer»", fill=(255, 255, 255), font=fonts["title"], anchor="mm")

    draw.text((540, 1750), "Y además... busca clientes nuevos »", fill=(148, 163, 184), font=fonts["body_bold"], anchor="mm")
    return img

def build_slide_5():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 4)
    draw_header_badge(draw, "PROSPECCIÓN AUTÓNOMA", color=(250, 204, 21))
    fonts = get_fonts()
    
    draw.text((540, 210), "Sofía sale a buscar\nclientes todos los días", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "Tu vendedora digital activa buscando compras:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")

    cards = [
        ("MAPS", "Rastreo en Google Maps", "Encuentra comercios, ferreterías, hoteles o negocios\nde tu zona que necesitan lo que vos vendés."),
        ("OUTREACH", "Contacta 12 a 15 empresas por día", "Les escribe de forma personalizada bajo tu marca\ncon tu propuesta comercial y lista de precios."),
        ("CIERRE", "Alerta de compra directo a tu celular", "Apenas un cliente responde interesado, te avisa en vivo\npara que llames o mandes al vendedor a cerrar.")
    ]

    y = 405
    for tag, title, desc in cards:
        draw.rounded_rectangle([80, y, 1000, y + 260], radius=26, fill=(17, 24, 39, 230), outline=(250, 204, 21, 150), width=2)
        pw = draw_pill(draw, tag, 120, y + 26, bg=(250, 204, 21, 30), border=(250, 204, 21, 200), text_color=(250, 204, 21))
        draw.text((120, y + 78), title, fill=(255, 255, 255), font=fonts["card_title"])
        draw.text((120, y + 138), desc, fill=(226, 232, 240), font=fonts["body"])
        y += 285

    draw.rounded_rectangle([80, 1315, 1000, 1615], radius=26, fill=(15, 23, 42, 240), outline=(37, 211, 102, 200), width=2)
    draw.text((540, 1385), "100% Oficial Meta Cloud API", fill=(37, 211, 102), font=fonts["title"], anchor="mm")
    draw.text((540, 1485), "Sin riesgo de baneo ni emuladores.\nInfraestructura empresarial en la nube activa 24/7.", fill=(255, 255, 255), font=fonts["subtitle"], anchor="mm", align="center")

    draw.text((540, 1750), "Probala gratis en vivo ahora »", fill=(37, 211, 102), font=fonts["body_bold"], anchor="mm")
    return img

def build_slide_6():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 5)
    draw_header_badge(draw, "PROBALA EN VIVO AHORA")
    fonts = get_fonts()
    
    av = get_circular_avatar(size=230)
    if av:
        img.paste(av, ((1080 - av.width) // 2, 200), av)
        draw = ImageDraw.Draw(img)

    draw.text((540, 500), "¿Querés ver a Sofía\nen tu negocio?", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 610), "Hacé la prueba vos mismo en 3 minutos:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")

    draw.rounded_rectangle([80, 690, 1000, 1250], radius=32, fill=(15, 34, 25, 250), outline=(37, 211, 102, 255), width=3)
    
    draw.text((540, 770), "Respondé a este estado con:", fill=(255, 255, 255), font=fonts["subtitle"], anchor="mm")
    draw.text((540, 890), "«DEMO»", fill=(37, 211, 102), font=fonts["cta_big"], anchor="mm")
    
    perks = [
        ("VÍDEO", "Te mandamos el video demo de 3 minutos"),
        ("CHAT", "Te damos acceso al chat de WhatsApp de Sofía"),
        ("PRECIOS", "Te mostramos cómo adaptarla a tu catálogo")
    ]
    y = 1000
    for tag, desc in perks:
        pw = draw_pill(draw, tag, 120, y, bg=(37, 211, 102, 40), border=(37, 211, 102, 220), text_color=(37, 211, 102))
        draw.text((120 + pw + 18, y + 2), desc, fill=(226, 232, 240), font=fonts["body_bold"])
        y += 75

    draw.rounded_rectangle([80, 1310, 1000, 1610], radius=28, fill=(15, 23, 42, 240), outline=(51, 65, 85, 200), width=2)
    draw.text((540, 1375), "O escribinos directo al WhatsApp:", fill=(148, 163, 184), font=fonts["body_bold"], anchor="mm")
    draw.text((540, 1455), "+54 9 343 572-0312", fill=(56, 189, 248), font=fonts["title"], anchor="mm")
    draw.text((540, 1535), "Mandá «DEMO» y te respondemos con el video al instante", fill=(37, 211, 102), font=fonts["body_bold"], anchor="mm")

    draw.text((540, 1750), "Cupos limitados de implementación bonificada", fill=(250, 204, 21), font=fonts["caption"], anchor="mm")
    return img

def main():
    os.makedirs("assets/slides", exist_ok=True)
    builders = [
        ("assets/slides/slide_1_portada.png", build_slide_1),
        ("assets/slides/slide_2_problema.png", build_slide_2),
        ("assets/slides/slide_3_modo_dueno.png", build_slide_3),
        ("assets/slides/slide_4_pedidos_deposito.png", build_slide_4),
        ("assets/slides/slide_5_prospeccion_maps.png", build_slide_5),
        ("assets/slides/slide_6_cta_demo.png", build_slide_6),
    ]
    for path, builder in builders:
        slide = builder()
        slide.save(path, "PNG", optimize=True)
        print(f"✅ Generated: {path}")

if __name__ == "__main__":
    main()
