# Export Tara logos from frontend/Desgin into the web app.
# Run with Pillow, mounting /in=frontend/Desgin (ro), /web=frontend/web and
# /prev=a preview folder, e.g.
#   docker run --rm --entrypoint python \
#     -v "$PWD/frontend/Desgin:/in:ro" -v "$PWD/frontend/web:/web" \
#     -v "$PWD/.logo-preview:/prev" \
#     -v "$PWD/scripts/brand/export_logos.py:/x.py:ro" tara/media:dev /x.py
from PIL import Image, ImageDraw

IN = "/in"
ASSETS = "/web/src/assets/brand"
ICONS = "/web/public/icons"
PREV = "/prev"


def trim(im, thr=10):
    a = im.getchannel("A").point(lambda v: 255 if v > thr else 0)
    return im.crop(a.getbbox())


def fit(im, max_side):
    w, h = im.size
    s = max_side / max(w, h)
    return im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)


def save(im, path):
    im.save(path, optimize=True)


en = trim(Image.open(f"{IN}/tara-en.png").convert("RGBA"))
en_w = trim(Image.open(f"{IN}/Glossy TARA Logo in English white.png").convert("RGBA"))
ar = trim(Image.open(f"{IN}/arabic/tara-logo-v2-ar.png").convert("RGBA"))
ar_w = trim(Image.open(f"{IN}/arabic/White Arabic Wordmark “تارا”.png").convert("RGBA"), 40)
ar_icon = trim(Image.open(f"{IN}/tara_logo-main-ar.png").convert("RGBA"))

# The English logo is tara-en-ve.png (colour, light themes) and
# tara-en-full-white.png (white, dark themes, photos and gradients); the
# Arabic ones are tara-logo-v2-ar.png and the white wordmark.
logo_en = trim(Image.open(f"{IN}/en-logo-at home/tara-en-ve.png").convert("RGBA"))
logo_en_white = trim(Image.open(f"{IN}/en-logo-at home/tara-en-full-white.png").convert("RGBA"))

for name, im in [
    ("tara-en", logo_en),
    ("tara-en-white", logo_en_white),
    ("tara-ar", ar),
    ("tara-ar-white", ar_w),
]:
    save(fit(im, 384), f"{ASSETS}/{name}.png")


def square(im, size, pad=0.0, bg=None):
    canvas = Image.new("RGBA", (size, size), bg or (0, 0, 0, 0))
    inner = round(size * (1 - 2 * pad))
    g = fit(im, inner)
    canvas.alpha_composite(g, ((size - g.width) // 2, (size - g.height) // 2))
    return canvas


def gradient_tile(size, radius_ratio=0.22, full_bleed=False):
    tile = Image.new("RGBA", (size, size))
    a = (0x6A, 0x00, 0xF4)
    b = (0xA8, 0x55, 0xF7)
    c = (0xFF, 0x4E, 0xD8)
    px = tile.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            if t < 0.6:
                k = t / 0.6
                col = tuple(round(a[i] + (b[i] - a[i]) * k) for i in range(3))
            else:
                k = (t - 0.6) / 0.4
                col = tuple(round(b[i] + (c[i] - b[i]) * k) for i in range(3))
            px[x, y] = col + (255,)
    if full_bleed:
        return tile
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=round(size * radius_ratio), fill=255
    )
    tile.putalpha(mask)
    return tile


def en_icon(size, full_bleed=False, pad=0.2):
    t = gradient_tile(size, full_bleed=full_bleed)
    g = fit(en_w, round(size * (1 - 2 * pad)))
    t.alpha_composite(g, ((size - g.width) // 2, (size - g.height) // 2))
    return t


def ar_app_icon(size, maskable=False):
    if maskable:
        t = gradient_tile(size, full_bleed=True)
        g = fit(ar_w, round(size * 0.62))
        t.alpha_composite(g, ((size - g.width) // 2, (size - g.height) // 2))
        return t
    return square(ar_icon, size)


for s in (192, 512):
    save(ar_app_icon(s), f"{ICONS}/icon-ar-{s}.png")
    save(en_icon(s), f"{ICONS}/icon-en-{s}.png")
save(ar_app_icon(512), f"{ICONS}/icon-512.png")
save(ar_app_icon(192), f"{ICONS}/icon-192.png")
save(ar_app_icon(512, maskable=True), f"{ICONS}/icon-maskable-512.png")
save(en_icon(512, full_bleed=True, pad=0.27), f"{ICONS}/icon-en-maskable-512.png")
# apple touch: opaque background required
ap = Image.new("RGBA", (180, 180), (0x0B, 0x0B, 0x1F, 255))
ap.alpha_composite(square(ar_icon, 180))
save(ap.convert("RGB"), f"{ICONS}/apple-touch-icon.png")
ap = Image.new("RGBA", (180, 180), (0x0B, 0x0B, 0x1F, 255))
ap.alpha_composite(en_icon(180))
save(ap.convert("RGB"), f"{ICONS}/apple-touch-icon-en.png")
# favicons
save(square(ar_icon, 64), f"{ICONS}/favicon-ar.png")
save(en_icon(64, pad=0.16), f"{ICONS}/favicon-en.png")
# notification badge: monochrome white silhouette on transparent
sil = fit(ar_w, 80)
alpha = sil.getchannel("A").point(lambda v: 255 if v > 110 else 0)
badge = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
w = Image.new("RGBA", sil.size, (255, 255, 255, 255))
w.putalpha(alpha)
badge.alpha_composite(w, ((96 - sil.width) // 2, (96 - sil.height) // 2))
save(badge, f"{ICONS}/badge-96.png")

# previews on light and dark backgrounds
for name in ("tara-en", "tara-en-white", "tara-ar", "tara-ar-white"):
    im = Image.open(f"{ASSETS}/{name}.png")
    for bgname, bg in (("light", (245, 245, 250, 255)), ("dark", (11, 11, 31, 255))):
        c = Image.new("RGBA", (im.width + 40, im.height + 40), bg)
        c.alpha_composite(im, (20, 20))
        c.convert("RGB").save(f"{PREV}/{name}-{bgname}.png")
sheet = Image.new("RGBA", (512 * 3 + 40, 512 + 20), (200, 200, 210, 255))
for i, f in enumerate(["icon-ar-512.png", "icon-en-512.png", "icon-maskable-512.png"]):
    sheet.alpha_composite(Image.open(f"{ICONS}/{f}"), (10 + i * 522, 10))
sheet.convert("RGB").save(f"{PREV}/icons.png")
print("done")
