import os
from PIL import Image, ImageDraw, ImageFont

def create_detailed_sofia_logo(output_path="assets/sofia_agency_logo.jpg", size=1024):
    # Base background: ultra deep dark slate
    img = Image.new("RGB", (size, size), "#090d16")
    draw = ImageDraw.Draw(img)

    cx, cy = size // 2, size // 2

    # Load fonts
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 94)
        font_agency = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        font_feature = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
        font_sub = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    except Exception:
        font_title = ImageFont.load_default()
        font_agency = ImageFont.load_default()
        font_feature = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    # Outer subtle ring with WhatsApp green & cyan gradient accents
    outer_r = 485
    draw.arc([cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r], start=0, end=360, fill="#1e293b", width=4)
    # WhatsApp green arc on top
    draw.arc([cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r], start=220, end=320, fill="#25d366", width=8)
    # Electric cyan arc on bottom
    draw.arc([cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r], start=40, end=140, fill="#06b6d4", width=8)

    # 1. ICON: Modern WhatsApp Chat Bubble with AI Neural Core
    bubble_cy = cy - 240
    bubble_w, bubble_h = 130, 105
    # Chat bubble pill
    draw.rounded_rectangle(
        [cx - bubble_w, bubble_cy - bubble_h, cx + bubble_w, bubble_cy + bubble_h - 20],
        radius=35,
        fill="#128c7e",
        outline="#25d366",
        width=5
    )
    # Bubble tail (pointing bottom left)
    tail = [
        (cx - 50, bubble_cy + bubble_h - 22),
        (cx - 95, bubble_cy + bubble_h + 20),
        (cx - 20, bubble_cy + bubble_h - 22)
    ]
    draw.polygon(tail, fill="#128c7e", outline="#25d366")
    # Clean inner tail fill to blend
    draw.line([(cx - 48, bubble_cy + bubble_h - 22), (cx - 22, bubble_cy + bubble_h - 22)], fill="#128c7e", width=7)

    # AI Sparkles / Neural Wave inside the bubble
    draw.arc([cx - 55, bubble_cy - 40, cx + 55, bubble_cy + 25], start=20, end=160, fill="#ffffff", width=8)
    # Sparkle star center
    star_x, star_y = cx, bubble_cy - 10
    draw.ellipse([star_x - 12, star_y - 12, star_x + 12, star_y + 12], fill="#ffffff")
    draw.line([star_x - 22, star_y, star_x + 22, star_y], fill="#ffffff", width=4)
    draw.line([star_x, star_y - 22, star_x, star_y + 22], fill="#ffffff", width=4)
    # Small satellite sparks
    draw.ellipse([star_x - 38, star_y - 25, star_x - 30, star_y - 17], fill="#67e8f9")
    draw.ellipse([star_x + 30, star_y + 10, star_x + 38, star_y + 18], fill="#67e8f9")

    # 2. BRAND TITLE: SOFÍA
    text_sofia = "SOFÍA"
    bbox_s = draw.textbbox((0, 0), text_sofia, font=font_title)
    w_s = bbox_s[2] - bbox_s[0]
    draw.text((cx - w_s // 2, cy - 90), text_sofia, fill="#ffffff", font=font_title)

    # 3. SUBTITLE: AGENCIA DE IA
    text_agency = "AGENCIA DE IA"
    bbox_ag = draw.textbbox((0, 0), text_agency, font=font_agency)
    w_ag = bbox_ag[2] - bbox_ag[0]
    draw.text((cx - w_ag // 2, cy + 30), text_agency, fill="#38bdf8", font=font_agency)

    # Sleek dividing separator with a green dot
    draw.line([cx - 180, cy + 90, cx - 25, cy + 90], fill="#334155", width=2)
    draw.ellipse([cx - 8, cy + 82, cx + 8, cy + 98], fill="#25d366")
    draw.line([cx + 25, cy + 90, cx + 180, cy + 90], fill="#334155", width=2)

    # 4. KEY BADGE: VENTAS Y ATENCIÓN 24/7
    # Badge background box
    badge_w, badge_h = 320, 36
    badge_y = cy + 145
    draw.rounded_rectangle(
        [cx - badge_w, badge_y - badge_h, cx + badge_w, badge_y + badge_h],
        radius=25,
        fill="#064e3b",
        outline="#10b981",
        width=3
    )
    # Live dot
    draw.ellipse([cx - badge_w + 35, badge_y - 10, cx - badge_w + 55, badge_y + 10], fill="#22c55e")
    text_va = "VENTAS Y ATENCIÓN 24/7"
    bbox_va = draw.textbbox((0, 0), text_va, font=font_feature)
    w_va = bbox_va[2] - bbox_va[0]
    draw.text((cx - w_va // 2 + 15, badge_y - 20), text_va, fill="#ffffff", font=font_feature)

    # 5. BENEFIT LINE: AUTOMATIZACIÓN PARA EMPRESAS
    text_auto = "Automatización para Empresas"
    bbox_au = draw.textbbox((0, 0), text_auto, font=font_sub)
    w_au = bbox_au[2] - bbox_au[0]
    draw.text((cx - w_au // 2, cy + 245), text_auto, fill="#94a3b8", font=font_sub)

    # 6. LOCATION ANCHOR: Paraná, Entre Ríos • Argentina
    text_loc = "Paraná, Entre Ríos • Argentina"
    try:
        font_loc = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 25)
    except Exception:
        font_loc = font_sub
    bbox_loc = draw.textbbox((0, 0), text_loc, font=font_loc)
    w_loc = bbox_loc[2] - bbox_loc[0]
    draw.text((cx - w_loc // 2, cy + 320), text_loc, fill="#38bdf8", font=font_loc)

    # Save PNG and JPG
    img.save(output_path, "JPEG", quality=95)
    img.save(output_path.replace(".jpg", ".png"), "PNG")
    print(f"✅ Detailed logo created at {output_path}")

if __name__ == "__main__":
    create_detailed_sofia_logo()
