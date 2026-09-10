import os
from PIL import Image, ImageDraw, ImageFont

def generate_combined_profile(
    avatar_path="assets/sofia_avatar.jpg",
    output_path="assets/sofia_profile_combined.jpg",
    size=1024
):
    avatar = Image.open(avatar_path).convert("RGBA")
    if avatar.size != (size, size):
        avatar = avatar.resize((size, size), Image.Resampling.LANCZOS)

    w, h = size, size
    cx, cy = w // 2, h // 2

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Fonts
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 62)
        font_agency = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
        font_badge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
        font_auto = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
        font_loc = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 19)
    except Exception:
        font_title = ImageFont.load_default()
        font_agency = ImageFont.load_default()
        font_badge = ImageFont.load_default()
        font_auto = ImageFont.load_default()
        font_loc = ImageFont.load_default()

    # 1. Dark gradient lower overlay (leaves face/shoulders visible, darkens lower third)
    for y in range(650, 1024):
        alpha = int(245 * ((y - 650) / (1024 - 650)) ** 1.2)
        draw.line([(0, y), (w, y)], fill=(9, 13, 22, alpha))

    # 2. Subtle cyan divider curve
    draw.arc([cx - 400, 655, cx + 400, 785], start=210, end=330, fill=(56, 189, 248, 160), width=3)

    # 3. Title: SOFÍA (y = 715)
    text_name = "SOFÍA"
    bbox_name = draw.textbbox((0, 0), text_name, font=font_title)
    wn = bbox_name[2] - bbox_name[0]
    draw.text((cx - wn // 2, 705), text_name, fill=(255, 255, 255, 255), font=font_title)

    # 4. Subtitle: AGENCIA DE IA (y = 780)
    text_sub = "AGENCIA DE IA"
    bbox_sub = draw.textbbox((0, 0), text_sub, font=font_agency)
    ws = bbox_sub[2] - bbox_sub[0]
    draw.text((cx - ws // 2, 780), text_sub, fill=(56, 189, 248, 255), font=font_agency)

    # 5. Pill Badge: ● VENTAS Y ATENCIÓN 24/7 (y = 835)
    badge_w, badge_h = 205, 22
    by = 835
    draw.rounded_rectangle(
        [cx - badge_w, by - badge_h, cx + badge_w, by + badge_h],
        radius=18,
        fill=(6, 78, 59, 240),
        outline=(16, 185, 129, 255),
        width=2
    )
    # Green pulsing dot
    draw.ellipse([cx - badge_w + 18, by - 6, cx - badge_w + 30, by + 6], fill=(34, 197, 94, 255))
    text_badge = "VENTAS Y ATENCIÓN 24/7"
    bbox_b = draw.textbbox((0, 0), text_badge, font=font_badge)
    wb = bbox_b[2] - bbox_b[0]
    draw.text((cx - wb // 2 + 10, by - 14), text_badge, fill=(255, 255, 255, 255), font=font_badge)

    # 6. Benefit line: Automatización para Empresas (y = 880)
    text_auto = "Automatización para Empresas"
    bbox_au = draw.textbbox((0, 0), text_auto, font=font_auto)
    w_au = bbox_au[2] - bbox_au[0]
    draw.text((cx - w_au // 2, 878), text_auto, fill=(148, 163, 184, 255), font=font_auto)

    # 7. Location Anchor: Paraná, Entre Ríos • Argentina (y = 925)
    text_loc = "Paraná, Entre Ríos • Argentina"
    bbox_loc = draw.textbbox((0, 0), text_loc, font=font_loc)
    w_loc = bbox_loc[2] - bbox_loc[0]
    draw.text((cx - w_loc // 2, 922), text_loc, fill=(56, 189, 248, 255), font=font_loc)

    # 8. Circular border accents (fits WhatsApp circle crop of radius 512)
    draw.arc([14, 14, w - 14, h - 14], start=0, end=360, fill=(30, 41, 59, 140), width=5)
    draw.arc([14, 14, w - 14, h - 14], start=210, end=330, fill=(37, 211, 102, 230), width=6)
    draw.arc([14, 14, w - 14, h - 14], start=40, end=140, fill=(6, 182, 212, 230), width=6)

    final_img = Image.alpha_composite(avatar, overlay)
    rgb_final = final_img.convert("RGB")
    rgb_final.save(output_path, "JPEG", quality=95)
    rgb_final.save(output_path.replace(".jpg", ".png"), "PNG")
    print(f"✅ Combined profile picture with full branding created at {output_path}")

if __name__ == "__main__":
    generate_combined_profile()
