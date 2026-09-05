import math
from PIL import Image, ImageDraw, ImageFont

def create_sofia_logo(output_path="assets/sofia_agency_logo.jpg", size=1024):
    # Create image with deep navy background
    img = Image.new("RGB", (size, size), "#070b14")
    draw = ImageDraw.Draw(img)

    cx, cy = size // 2, size // 2

    # Draw subtle background glow
    for r in range(450, 200, -10):
        alpha = int(25 * (1 - (r - 200) / 250))
        glow_color = (16, 35, 70)
        draw.ellipse([cx - r, cy - r - 40, cx + r, cy + r - 40], fill=glow_color)

    # Outer decorative tech ring
    ring_radius = 420
    draw.arc([cx - ring_radius, cy - ring_radius - 40, cx + ring_radius, cy + ring_radius - 40],
             start=0, end=360, fill="#1e293b", width=4)

    # Cyan glowing tech accents along the ring
    draw.arc([cx - ring_radius, cy - ring_radius - 40, cx + ring_radius, cy + ring_radius - 40],
             start=30, end=110, fill="#06b6d4", width=8)
    draw.arc([cx - ring_radius, cy - ring_radius - 40, cx + ring_radius, cy + ring_radius - 40],
             start=210, end=290, fill="#3b82f6", width=8)

    # Inner circular boundary
    inner_r = 380
    draw.arc([cx - inner_r, cy - inner_r - 40, cx + inner_r, cy + inner_r - 40],
             start=0, end=360, fill="#0f172a", width=6)

    # Draw stylized geometric AI "S" Monogram in the center
    # Top arc of S
    draw.arc([cx - 130, cy - 260, cx + 90, cy - 80], start=140, end=360, fill="#38bdf8", width=36)
    # Bottom arc of S
    draw.arc([cx - 90, cy - 140, cx + 130, cy + 40], start=0, end=220, fill="#06b6d4", width=36)
    # Diagonal connecting bar
    draw.line([cx + 60, cy - 110, cx - 60, cy - 20], fill="#38bdf8", width=36)

    # Glowing connection nodes (AI neurons)
    nodes = [
        (cx - 120, cy - 150),
        (cx + 80, cy - 240),
        (cx - 50, cy - 65),
        (cx + 50, cy - 65),
        (cx - 80, cy + 20),
        (cx + 120, cy - 70)
    ]
    for nx, ny in nodes:
        draw.ellipse([nx - 14, ny - 14, nx + 14, ny + 14], fill="#67e8f9", outline="#0284c7", width=3)
        draw.ellipse([nx - 6, ny - 6, nx + 6, ny + 6], fill="#ffffff")

    # Load system font or default
    try:
        font_main = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 96)
        font_sub = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
    except Exception:
        font_main = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    # Brand Title: SOFÍA
    text_main = "SOFÍA"
    bbox_main = draw.textbbox((0, 0), text_main, font=font_main)
    w_main = bbox_main[2] - bbox_main[0]
    draw.text((cx - w_main // 2, cy + 130), text_main, fill="#ffffff", font=font_main)

    # Brand Subtitle: AGENCIA DE IA
    text_sub = "AGENCIA DE IA"
    bbox_sub = draw.textbbox((0, 0), text_sub, font=font_sub)
    w_sub = bbox_sub[2] - bbox_sub[0]
    draw.text((cx - w_sub // 2, cy + 245), text_sub, fill="#38bdf8", font=font_sub)

    # Thin sleek badge line below
    draw.line([cx - 160, cy + 305, cx + 160, cy + 305], fill="#1e293b", width=3)
    draw.line([cx - 70, cy + 305, cx + 70, cy + 305], fill="#06b6d4", width=5)

    # Save outputs
    img.save(output_path, "JPEG", quality=95)
    img.save(output_path.replace(".jpg", ".png"), "PNG")
    print(f"✅ Logo created successfully at {output_path}")

if __name__ == "__main__":
    create_sofia_logo()
