from PIL import Image, ImageDraw, ImageFont
import colorsys
import os

OUTPUT_DIR = "sample_slideshow_images"
os.makedirs(OUTPUT_DIR, exist_ok=True)

RESOLUTIONS = [
    (640, 480),
    (800, 600),
    (1024, 768),
    (1280, 720),
    (1280, 800),
    (1366, 768),
    (1600, 900),
    (1920, 1080),
    (1920, 1200),
    (2560, 1440),
    (3840, 2160),
    (1080, 1920),
    (1440, 2560),
    (1200, 1200),
    (2048, 2048),
]

def get_font(size):
    return ImageFont.truetype("DejaVuSans.ttf", size)

for i, (width, height) in enumerate(RESOLUTIONS, start=1):

    hue = (i - 1) / len(RESOLUTIONS)
    r, g, b = colorsys.hsv_to_rgb(hue, 0.75, 0.95)

    image = Image.new(
        "RGB",
        (width, height),
        (int(r * 255), int(g * 255), int(b * 255))
    )

    draw = ImageDraw.Draw(image)

    big_font_size = max(48, min(width, height) // 4)
    small_font_size = max(20, min(width, height) // 20)

    big_font = get_font(big_font_size)
    small_font = get_font(small_font_size)

    number_text = str(i)
    resolution_text = f"{width} × {height}"

    nb = draw.textbbox((0, 0), number_text, font=big_font)
    rb = draw.textbbox((0, 0), resolution_text, font=small_font)

    number_w = nb[2] - nb[0]
    number_h = nb[3] - nb[1]

    res_w = rb[2] - rb[0]
    res_h = rb[3] - rb[1]

    spacing = max(10, height // 50)
    total_h = number_h + spacing + res_h

    y = (height - total_h) // 2

    center_x = width // 2

    draw.text(
        (center_x, height // 2 - big_font_size // 3),
        number_text,
        font=big_font,
        fill="white",
        anchor="mm"
    )

    draw.text(
        (center_x, height // 2 + big_font_size // 3),
        resolution_text,
        font=small_font,
        fill="white",
        anchor="mm"
    )

    filename = f"{i}.png"
    image.save(os.path.join(OUTPUT_DIR, filename))

print(f"Generated {len(RESOLUTIONS)} images.")