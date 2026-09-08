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

def draw_story_bars(draw, active_index, total=7):
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
    draw_header_badge(draw, "SOFIA • AGÊNCIA DE IA")
    fonts = get_fonts()
    
    av = get_circular_avatar(size=280)
    if av:
        img.paste(av, ((1080 - av.width) // 2, 210), av)
        draw = ImageDraw.Draw(img)
    
    draw.rounded_rectangle([440, 520, 640, 568], radius=24, fill=(15, 23, 42, 250), outline=(37, 211, 102, 255), width=2)
    draw.ellipse([460, 538, 474, 552], fill=(37, 211, 102, 255))
    draw.text((490, 532), "ONLINE 24/7", fill=(255, 255, 255), font=fonts["caption"])

    draw.text((540, 645), "Conheça a Sofia", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm")
    
    sub = "A executiva comercial com IA que atende,\ncota e vende no seu WhatsApp\ncom a marca e preços da sua empresa."
    draw.text((540, 770), sub, fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm", align="center")
    
    draw.rounded_rectangle([80, 890, 1000, 1630], radius=32, fill=(17, 24, 39, 230), outline=(51, 65, 85, 180), width=2)
    
    items = [
        ("MAPS", "Busca novos clientes todo dia", "Entra em contato com 12 a 15 empresas por dia."),
        ("EXCEL", "Carrega suas tabelas de preços", "Atualiza preços e promoções no mesmo segundo."),
        ("ÁUDIO", "Entende mensagens de voz", "Recebe pedidos complexos e calcula o total exato."),
        ("ESTOQUE", "Envia o pedido pronto para entrega", "Com romaneio organizado para despachar sem demora.")
    ]
    
    y = 940
    for tag, title, desc in items:
        pw = draw_pill(draw, tag, 120, y)
        draw.text((120 + pw + 18, y + 2), title, fill=(255, 255, 255), font=fonts["body_bold"])
        draw.text((120, y + 55), desc, fill=(148, 163, 184), font=fonts["body"])
        y += 165

    draw.text((540, 1750), "Arraste para ver como funciona »", fill=(37, 211, 102), font=fonts["subtitle"], anchor="mm")
    return img

def build_slide_2():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 1)
    draw_header_badge(draw, "A DOR DE TODO NEGÓCIO", color=(248, 113, 113))
    fonts = get_fonts()
    
    draw.text((540, 210), "Cansado de perder vendas\nfora do horário comercial?", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "Os 3 problemas diários de distribuidoras e empresas:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")
    
    problems = [
        ("1", "Mensagens sem resposta à noite", "Seus clientes pedem preços às 21h ou domingo.\nSe ninguém responde rápido, compram de outro."),
        ("2", "Horas passando preços manualmente", "Sua equipe atolada respondendo as mesmas coisas\n50 vezes por dia em vez de focar nas vendas."),
        ("3", "Pedidos travados ou com erros de conta", "Áudios longos, contas no papel e atrasos para\npassar a ordem de separação para o estoque.")
    ]
    
    y = 405
    for num, title, desc in problems:
        draw.rounded_rectangle([80, y, 1000, y + 260], radius=26, fill=(24, 18, 26, 220), outline=(239, 68, 68, 160), width=2)
        pw = draw_pill(draw, f"PROBLEMA {num}", 120, y + 26, bg=(239, 68, 68, 40), border=(239, 68, 68, 200), text_color=(252, 165, 165))
        draw.text((120, y + 78), title, fill=(252, 165, 165), font=fonts["card_title"])
        draw.text((120, y + 138), desc, fill=(203, 213, 225), font=fonts["body"])
        y += 285

    draw.rounded_rectangle([80, 1315, 1000, 1615], radius=26, fill=(15, 34, 25, 240), outline=(37, 211, 102, 200), width=2)
    draw.text((540, 1385), "A Solução com a Sofia:", fill=(37, 211, 102), font=fonts["title"], anchor="mm")
    draw.text((540, 1485), "Atendimento imediato 24/7, contas exatas\ne os pedidos prontos para separar em 1 segundo.", fill=(255, 255, 255), font=fonts["subtitle"], anchor="mm", align="center")

    draw.text((540, 1750), "Veja como o dono controla tudo »", fill=(148, 163, 184), font=fonts["body_bold"], anchor="mm")
    return img

def build_slide_3():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 2)
    draw_header_badge(draw, "SEM SISTEMAS COMPLICADOS", color=(56, 189, 248))
    fonts = get_fonts()
    
    draw.text((540, 210), "Todo o controle direto do\nseu próprio WhatsApp", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "Sem senhas, sem instalar nada, sem precisar treinar equipe.", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")
    
    cards = [
        ("EXCEL", "1. Você envia sua tabela de preços", "A Sofia lê seu arquivo em segundos, aprende os\nprodutos e vende sempre com seus preços atualizados."),
        ("ÁUDIO", "2. Você dá instruções por áudio", "«Sofi, pedido mínimo de R$ 500 para frete grátis\ne entregamos só no centro». Ela aprende na hora."),
        ("MÉTRICAS", "3. Você pede relatórios quando quiser", "Escreve «resumo» e ela informa quantos pedidos entraram,\nquantos clientes falaram e o status da linha.")
    ]
    
    y = 405
    for tag, title, desc in cards:
        draw.rounded_rectangle([80, y, 1000, y + 260], radius=26, fill=(17, 24, 39, 230), outline=(56, 189, 248, 160), width=2)
        pw = draw_pill(draw, tag, 120, y + 26, bg=(56, 189, 248, 40), border=(56, 189, 248, 200), text_color=(56, 189, 248))
        draw.text((120, y + 78), title, fill=(255, 255, 255), font=fonts["card_title"])
        draw.text((120, y + 138), desc, fill=(226, 232, 240), font=fonts["body"])
        y += 285

    draw.rounded_rectangle([80, 1315, 1000, 1615], radius=26, fill=(15, 23, 42, 240), outline=(51, 65, 85, 220), width=2)
    draw.text((540, 1385), "100% na palma da sua mão", fill=(255, 255, 255), font=fonts["title"], anchor="mm")
    draw.text((540, 1485), "O empresário comanda a empresa conversando com a Sofia\ncomo se fosse sua assessora de máxima confiança.", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm", align="center")

    draw.text((540, 1750), "Veja como ela atualiza preços no Excel »", fill=(37, 211, 102), font=fonts["body_bold"], anchor="mm")
    return img

def build_slide_precios():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 3)
    draw_header_badge(draw, "ADEUS HORAS DE EXCEL MANUAL", color=(52, 211, 153))
    fonts = get_fonts()
    
    draw.text((540, 210), "O fornecedor aumentou?\nA Sofia cruza as tabelas por você", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "Atualize preços e catálogo em 1 segundo sem trabalho manual:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")
    
    cards = [
        ("PASSO 1", "Você envia as 2 tabelas pelo WhatsApp", "Sua tabela atual desatualizada + o Excel novo que o\nfornecedor ou a fábrica mandou com os aumentos."),
        ("PASSO 2", "Cruzamento semântico inteligente com IA", "A Sofia cruza os produtos mesmo que os nomes variem\n(ex: «Coca 1.5L» com «Refrigerante Coca-Cola 1500ml»)."),
        ("PASSO 3", "Preços ao vivo e Excel recalculado", "A Sofia começa a cotar com os preços novos na hora\ne devolve a planilha pronta para usar ou imprimir.")
    ]
    
    y = 405
    for tag, title, desc in cards:
        draw.rounded_rectangle([80, y, 1000, y + 260], radius=26, fill=(17, 24, 39, 230), outline=(52, 211, 153, 160), width=2)
        pw = draw_pill(draw, tag, 120, y + 26, bg=(52, 211, 153, 35), border=(52, 211, 153, 200), text_color=(52, 211, 153))
        draw.text((120, y + 78), title, fill=(255, 255, 255), font=fonts["card_title"])
        draw.text((120, y + 138), desc, fill=(226, 232, 240), font=fonts["body"])
        y += 285

    draw.rounded_rectangle([80, 1315, 1000, 1615], radius=26, fill=(15, 34, 25, 240), outline=(37, 211, 102, 220), width=2)
    draw.text((540, 1385), "Adeus fórmulas e planilhas quebradas", fill=(37, 211, 102), font=fonts["title"], anchor="mm")
    draw.text((540, 1485), "Sem PROCV, sem erros de digitação e sem trocar\npreços à mão. Suas vendas sempre em dia 24/7.", fill=(255, 255, 255), font=fonts["subtitle"], anchor="mm", align="center")

    draw.text((540, 1750), "Veja como ela recebe um pedido ao vivo »", fill=(37, 211, 102), font=fonts["body_bold"], anchor="mm")
    return img

def build_slide_4():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 4)
    draw_header_badge(draw, "OPERAÇÃO AO VIVO")
    fonts = get_fonts()
    
    draw.text((540, 210), "Da mensagem ao estoque\nem 1 segundo", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "Veja o fluxo automático passo a passo:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")

    steps = [
        ("PASSO 1", "O cliente escreve ou manda áudio:", "«Me manda 1 caixa de óleo e 2 fardos de farinha.»", (255, 255, 255)),
        ("PASSO 2", "A Sofia calcula com matemática exata:", "• 1x Óleo: R$ 140  |  2x Farinha: R$ 250\nTOTAL ESTIMADO: R$ 390. Posso confirmar?", (37, 211, 102)),
        ("PASSO 3", "O cliente confirma o pedido:", "«Sim, pode fechar». A Sofia registra a venda no sistema.", (56, 189, 248)),
        ("PASSO 4", "Alerta imediato para o estoque / dono:", "Chega no WhatsApp do estoque a lista pronta para separar\ne os dados do cliente para despachar.", (250, 204, 21))
    ]

    y = 405
    for tag, step_title, step_desc, accent in steps:
        h = 245 if "\n" in step_desc else 185
        draw.rounded_rectangle([80, y, 1000, y + h], radius=24, fill=(15, 23, 42, 240), outline=(51, 65, 85, 200), width=2)
        pw = draw_pill(draw, tag, 110, y + 22, bg=(30, 41, 59, 220), border=accent, text_color=accent)
        draw.text((110 + pw + 16, y + 24), step_title, fill=(255, 255, 255), font=fonts["body_bold"])
        draw.text((110, y + 78), step_desc, fill=accent if tag == "PASSO 2" else (226, 232, 240), font=fonts["body"])
        y += h + 20

    draw.rounded_rectangle([80, 1370, 1000, 1630], radius=26, fill=(20, 33, 25, 240), outline=(37, 211, 102, 200), width=2)
    draw.text((540, 1450), "«Faço o trabalho repetitivo", fill=(37, 211, 102), font=fonts["title"], anchor="mm")
    draw.text((540, 1530), "que ninguém quer fazer»", fill=(255, 255, 255), font=fonts["title"], anchor="mm")

    draw.text((540, 1750), "E tem mais... ela busca novos clientes »", fill=(148, 163, 184), font=fonts["body_bold"], anchor="mm")
    return img

def build_slide_5():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 5)
    draw_header_badge(draw, "PROSPECÇÃO ATIVA", color=(250, 204, 21))
    fonts = get_fonts()
    
    draw.text((540, 210), "A Sofia busca novos\nclientes todos os dias", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 335), "Sua vendedora digital em busca de novas vendas:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")

    cards = [
        ("MAPS", "Busca no Google Maps", "Encontra mercados, padarias, lojas ou hotéis da sua\nregião que precisam exatamente do que você vende."),
        ("OUTREACH", "Contata 12 a 15 empresas por dia", "Envia mensagens personalizadas em nome da sua marca\ncom sua proposta comercial e catálogo de produtos."),
        ("FECHAMENTO", "Alerta de compra direto no seu celular", "Assim que um cliente responde com interesse, você recebe o aviso\npara negociar e fechar o pedido na hora.")
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
    draw.text((540, 1485), "Sem risco de bloqueio, sem emuladores.\nInfraestrutura corporativa em nuvem ativa 24/7.", fill=(255, 255, 255), font=fonts["subtitle"], anchor="mm", align="center")

    draw.text((540, 1750), "Teste grátis agora mesmo »", fill=(37, 211, 102), font=fonts["body_bold"], anchor="mm")
    return img

def build_slide_6():
    img = create_base_canvas()
    draw = ImageDraw.Draw(img)
    draw_story_bars(draw, 6)
    draw_header_badge(draw, "TESTE AO VIVO AGORA")
    fonts = get_fonts()
    
    av = get_circular_avatar(size=230)
    if av:
        img.paste(av, ((1080 - av.width) // 2, 200), av)
        draw = ImageDraw.Draw(img)

    draw.text((540, 500), "Quer ver a Sofia no\nseu negócio?", fill=(255, 255, 255), font=fonts["title_xl"], anchor="mm", align="center")
    draw.text((540, 610), "Faça o teste você mesmo em 3 minutos:", fill=(148, 163, 184), font=fonts["subtitle"], anchor="mm")

    draw.rounded_rectangle([80, 690, 1000, 1250], radius=32, fill=(15, 34, 25, 250), outline=(37, 211, 102, 255), width=3)
    
    draw.text((540, 770), "Responda a este status com:", fill=(255, 255, 255), font=fonts["subtitle"], anchor="mm")
    draw.text((540, 890), "«DEMO»", fill=(37, 211, 102), font=fonts["cta_big"], anchor="mm")
    
    perks = [
        ("VÍDEO", "Enviamos o vídeo demonstrativo de 3 minutos"),
        ("CHAT", "Liberamos o WhatsApp da Sofia para você testar"),
        ("TABELA", "Mostramos como adaptar ao seu catálogo")
    ]
    y = 1000
    for tag, desc in perks:
        pw = draw_pill(draw, tag, 120, y, bg=(37, 211, 102, 40), border=(37, 211, 102, 220), text_color=(37, 211, 102))
        draw.text((120 + pw + 18, y + 2), desc, fill=(226, 232, 240), font=fonts["body_bold"])
        y += 75

    draw.rounded_rectangle([80, 1310, 1000, 1610], radius=28, fill=(15, 23, 42, 240), outline=(51, 65, 85, 200), width=2)
    draw.text((540, 1375), "Ou fale diretamente no WhatsApp:", fill=(148, 163, 184), font=fonts["body_bold"], anchor="mm")
    draw.text((540, 1455), "+54 9 343 572-0312", fill=(56, 189, 248), font=fonts["title"], anchor="mm")
    draw.text((540, 1535), "Envie «DEMO» e respondemos com o vídeo na hora", fill=(37, 211, 102), font=fonts["body_bold"], anchor="mm")

    draw.text((540, 1750), "Vagas limitadas para implementação personalizada", fill=(250, 204, 21), font=fonts["caption"], anchor="mm")
    return img

def main():
    out_dir = "assets/slides_pt"
    os.makedirs(out_dir, exist_ok=True)
    builders = [
        (f"{out_dir}/slide_1_portada.png", build_slide_1),
        (f"{out_dir}/slide_2_problema.png", build_slide_2),
        (f"{out_dir}/slide_3_modo_dueno.png", build_slide_3),
        (f"{out_dir}/slide_4_actualizacion_precios.png", build_slide_precios),
        (f"{out_dir}/slide_5_pedidos_deposito.png", build_slide_4),
        (f"{out_dir}/slide_6_prospeccion_maps.png", build_slide_5),
        (f"{out_dir}/slide_7_cta_demo.png", build_slide_6),
    ]
    for path, builder in builders:
        slide = builder()
        slide.save(path, "PNG", optimize=True)
        print(f"✅ Generated (PT-BR): {path}")

if __name__ == "__main__":
    main()

