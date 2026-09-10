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

    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 68)
        font_agency = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
        font_badge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
    except Exception:
        font_title = ImageFont.load_default()
        font_agency = ImageFont.load_default()
        font_badge = ImageFont.load_default()

    for y in range(680, 1024):
        alpha = int(230 * ((y - 680) / (1024 - 680)) ** 1.3)
        draw.line([(0, y), (w, y)], fill=(9, 13, 22, alpha))

    draw.arc([cx - 420, 690, cx + 420, 830], start=210, end=330, fill=(56, 189, 248, 180), width=3)

    text_name = "SOFÍA"
    bbox_name = draw.textbbox((0, 0), text_name, font=font_title)
    wn = bbox_name[2] - bbox_name[0]
    draw.text((cx - wn // 2, 755), text_name, fill=(255, 255, 255, 255), font=font_title)

    text_sub = "AGENCIA DE IA"
    bbox_sub = draw.textbbox((0, 0), text_sub, font=font_agency)
    ws = bbox_sub[2] - bbox_sub[0]
    draw.text((cx - ws // 2, 835), text_sub, fill=(56, 189, 248, 255), font=font_agency)

    badge_w, badge_h = 240, 26
    by = 905
    draw.rounded_rectangle(
        [cx - badge_w, by - badge_h, cx + badge_w, by + badge_h],
        radius=20,
        fill=(6, 78, 59, 235),
        outline=(16, 185, 129, 255),
        width=2
    )
    draw.ellipse([cx - badge_w + 22, by - 7, cx - badge_w + 36, by + 7], fill=(34, 197, 94, 255))
    text_badge = "VENTAS Y ATENCIÓN 24/7"
    bbox_b = draw.textbbox((0, 0), text_badge, font=font_badge)
    wb = bbox_b[2] - bbox_b[0]
    draw.text((cx - wb // 2 + 12, by - 16), text_badge, fill=(255, 255, 255, 255), font=font_badge)

    draw.arc([16, 16, w - 16, h - 16], start=0, end=360, fill=(30, 41, 59, 150), width=6)
    draw.arc([16, 16, w - 16, h - 16], start=210, end=330, fill=(37, 211, 102, 230), width=6)
    draw.arc([16, 16, w - 16, h - 16], start=40, end=140, fill=(6, 182, 212, 230), width=6)

    final_img = Image.alpha_composite(avatar, overlay)
    rgb_final = final_img.convert("RGB")
    rgb_final.save(output_path, "JPEG", quality=95)
    rgb_final.save(output_path.replace(".jpg", ".png"), "PNG")
    print(f"✅ Combined profile picture created at {output_path}")

if __name__ == "__main__":
    generate_combined_profile()
