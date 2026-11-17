import os
from PIL import Image, ImageDraw, ImageFont

def create_detailed_sofia_logo(output_path="/home/usuario/work/proyecto_gemini_cli/sofia_ai_agency/assets/sofia_agency_logo.jpg", size=1024):
    # Base background: ultra deep dark slate matching landing page (--bg-main: #0D0F12)
    img = Image.new("RGB", (size, size), "#0D0F12")
    draw = ImageDraw.Draw(img)

    cx, cy = size // 2, size // 2

    # Load system fonts
    font_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_reg = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    font_title = ImageFont.truetype(font_bold, 96)
    font_subtitle = ImageFont.truetype(font_bold, 32)
    font_badge = ImageFont.truetype(font_bold, 25)
    font_sub = ImageFont.truetype(font_reg, 26)

    # Outer subtle ring with emerald & cyan accents
    outer_r = 485
    draw.arc([cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r], start=0, end=360, fill="#1c212a", width=4)
    # Emerald green arc on top-left
    draw.arc([cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r], start=210, end=320, fill="#10b981", width=8)
    # Electric cyan arc on bottom-right
    draw.arc([cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r], start=40, end=140, fill="#06b6d4", width=8)

    # 1. ICON: Modern AI Neural Core inside Tech Badge
    bubble_cy = cy - 240
    bubble_w, bubble_h = 130, 105
    # Tech card pill
    draw.rounded_rectangle(
        [cx - bubble_w, bubble_cy - bubble_h, cx + bubble_w, bubble_cy + bubble_h - 20],
        radius=35,
        fill="#064e3b",
        outline="#10b981",
        width=5
    )
    # Bubble tail (pointing bottom left)
    tail = [
        (cx - 50, bubble_cy + bubble_h - 22),
        (cx - 95, bubble_cy + bubble_h + 20),
        (cx - 20, bubble_cy + bubble_h - 22)
    ]
    draw.polygon(tail, fill="#064e3b", outline="#10b981")
    # Clean inner tail fill
    draw.line([(cx - 48, bubble_cy + bubble_h - 22), (cx - 22, bubble_cy + bubble_h - 22)], fill="#064e3b", width=7)

    # Neural Wave / AI Sparkles
    draw.arc([cx - 55, bubble_cy - 40, cx + 55, bubble_cy + 25], start=20, end=160, fill="#ffffff", width=8)
    # Sparkle star center
    star_x, star_y = cx, bubble_cy - 10
    draw.ellipse([star_x - 12, star_y - 12, star_x + 12, star_y + 12], fill="#ffffff")
    draw.line([star_x - 22, star_y, star_x + 22, star_y], fill="#ffffff", width=4)
    draw.line([star_x, star_y - 22, star_x, star_y + 22], fill="#ffffff", width=4)
    # Satellite sparks
    draw.ellipse([star_x - 38, star_y - 25, star_x - 30, star_y - 17], fill="#6ee7b7")
    draw.ellipse([star_x + 30, star_y + 10, star_x + 38, star_y + 18], fill="#38bdf8")

    # 2. BRAND TITLE: "SOF-IA" (SOF in white, -IA in emerald green #10B981)
    bbox_sof = draw.textbbox((0, 0), "SOF", font=font_title)
    w_sof = bbox_sof[2] - bbox_sof[0]
    bbox_ia = draw.textbbox((0, 0), "-IA", font=font_title)
    w_ia = bbox_ia[2] - bbox_ia[0]
    total_w = w_sof + w_ia
    start_x = cx - (total_w // 2)

    title_y = cy - 90
    draw.text((start_x, title_y), "SOF", fill="#FFFFFF", font=font_title)
    draw.text((start_x + w_sof, title_y), "-IA", fill="#10B981", font=font_title)

    # 3. SUBTITLE: "TECH & AI STUDIO" (with refined letter spacing)
    text_studio = "T E C H   &   A I   S T U D I O"
    bbox_st = draw.textbbox((0, 0), text_studio, font=font_subtitle)
    w_st = bbox_st[2] - bbox_st[0]
    draw.text((cx - w_st // 2, cy + 30), text_studio, fill="#94A3B8", font=font_subtitle)

    # Sleek dividing separator with emerald glowing dot
    draw.line([cx - 200, cy + 90, cx - 30, cy + 90], fill="#262e3d", width=2)
    draw.ellipse([cx - 8, cy + 82, cx + 8, cy + 98], fill="#10b981")
    draw.line([cx + 30, cy + 90, cx + 200, cy + 90], fill="#262e3d", width=2)

    # 4. KEY BADGE: "SOFTWARE • AUTOMATIZACIÓN • IOT"
    badge_y = cy + 145
    text_badge = "SOFTWARE • AUTOMATIZACIÓN • IOT"
    bbox_badge = draw.textbbox((0, 0), text_badge, font=font_badge)
    w_badge = bbox_badge[2] - bbox_badge[0]
    h_badge = bbox_badge[3] - bbox_badge[1]

    dot_size = 12
    dot_gap = 14
    content_w = dot_size + dot_gap + w_badge
    start_bx = cx - (content_w // 2)

    pad_x = 24
    pad_y = 13
    draw.rounded_rectangle(
        [start_bx - pad_x, badge_y - pad_y, start_bx + content_w + pad_x, badge_y + h_badge + pad_y],
        radius=20,
        fill="#064e3b",
        outline="#10b981",
        width=2
    )
    # Green live dot
    dot_y = badge_y + (h_badge - dot_size) // 2
    draw.ellipse([start_bx, dot_y, start_bx + dot_size, dot_y + dot_size], fill="#34d399")
    # Clean text
    draw.text((start_bx + dot_size + dot_gap, badge_y), text_badge, fill="#FFFFFF", font=font_badge)

    # 5. BENEFIT LINE / PRODUCTS: "Actualizador PRO • Air Control • Soluciones AI"
    text_prod = "Actualizador PRO • Air Control • Soluciones AI"
    bbox_p = draw.textbbox((0, 0), text_prod, font=font_sub)
    w_p = bbox_p[2] - bbox_p[0]
    draw.text((cx - w_p // 2, cy + 245), text_prod, fill="#64748b", font=font_sub)

    # Save to sofia_ai_agency
    img.save(output_path, "JPEG", quality=95)
    img.save(output_path.replace(".jpg", ".png"), "PNG")
    
    # Also save directly in actualizador_precios_pro
    act_path_jpg = "/home/usuario/work/proyecto_gemini_cli/actualizador_precios_pro/sofia_agency_logo.jpg"
    act_path_png = "/home/usuario/work/proyecto_gemini_cli/actualizador_precios_pro/sofia_agency_logo.png"
    img.save(act_path_jpg, "JPEG", quality=95)
    img.save(act_path_png, "PNG")

    print(f"✅ Logo actualizado generado en:")
    print(f"   -> {output_path}")
    print(f"   -> {act_path_jpg}")

if __name__ == "__main__":
    create_detailed_sofia_logo()
