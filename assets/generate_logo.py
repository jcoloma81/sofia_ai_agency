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

    # 3. SUBTITLE: AUTOMATIZACIÓN INTELIGENTE
    text_agency = "AUTOMATIZACIÓN"
    bbox_ag = draw.textbbox((0, 0), text_agency, font=font_agency)
    w_ag = bbox_ag[2] - bbox_ag[0]
    draw.text((cx - w_ag // 2, cy + 30), text_agency, fill="#38bdf8", font=font_agency)

    # Sleek dividing separator with a green dot
    draw.line([cx - 180, cy + 90, cx - 25, cy + 90], fill="#334155", width=2)
    draw.ellipse([cx - 8, cy + 82, cx + 8, cy + 98], fill="#25d366")
    draw.line([cx + 25, cy + 90, cx + 180, cy + 90], fill="#334155", width=2)

    # 4. KEY BADGE: WHATSAPP & ERP EN TIEMPO REAL
    badge_y = cy + 150
    text_va = "WHATSAPP & ERP EN TIEMPO REAL"
    try:
        font_feature = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
    except Exception:
        font_feature = font_sub

    bbox_va = draw.textbbox((0, 0), text_va, font=font_feature)
    w_va = bbox_va[2] - bbox_va[0]
    h_va = bbox_va[3] - bbox_va[1]

    dot_size = 14
    dot_gap = 14
    content_w = dot_size + dot_gap + w_va
    start_x = cx - (content_w // 2)

    pad_x = 26
    pad_y = 14
    draw.rounded_rectangle(
        [start_x - pad_x, badge_y - pad_y, start_x + content_w + pad_x, badge_y + h_va + pad_y],
        radius=22,
        fill="#064e3b",
        outline="#10b981",
        width=3
    )
    # Green live dot (completely separated to the left)
    dot_y = badge_y + (h_va - dot_size) // 2
    draw.ellipse([start_x, dot_y, start_x + dot_size, dot_y + dot_size], fill="#22c55e")
    # Crisp white text safely to the right of the dot
    draw.text((start_x + dot_size + dot_gap, badge_y), text_va, fill="#ffffff", font=font_feature)

    # 5. BENEFIT LINE: Python • FastAPI • Gemini Multimodal
    text_auto = "Python • FastAPI • Gemini Multimodal"
    bbox_au = draw.textbbox((0, 0), text_auto, font=font_sub)
    w_au = bbox_au[2] - bbox_au[0]
    draw.text((cx - w_au // 2, cy + 250), text_auto, fill="#94a3b8", font=font_sub)

    # Save PNG and JPG
    img.save(output_path, "JPEG", quality=95)
    img.save(output_path.replace(".jpg", ".png"), "PNG")
    print(f"✅ Detailed logo created at {output_path}")

if __name__ == "__main__":
    create_detailed_sofia_logo()
