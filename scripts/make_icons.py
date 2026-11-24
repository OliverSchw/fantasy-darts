"""Erzeugt die App-Icons von Mönninghausen Games: Pokal mit Dartscheibe + Dart, daneben ein Bierkrug.

Aufruf: python scripts/make_icons.py  (schreibt nach app/static/icons/)
Nach einer Änderung die Versionsnummer ?v=... in base.html und manifest.webmanifest erhöhen,
sonst zeigen Browser und Handys das alte Bild aus dem Cache.
Gezeichnet wird in 4-facher Größe und dann herunterskaliert (glatte Kanten).
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"
S = 4096  # Zeichenfläche (4x 1024)

BG_TOP, BG_BOTTOM = (36, 112, 214), (10, 42, 92)
GOLD, GOLD_DARK, GOLD_LIGHT = (242, 193, 78), (196, 140, 22), (255, 226, 140)
RED, BOARD_GREEN, CREAM, BLACK = (214, 52, 60), (30, 143, 78), (243, 230, 196), (29, 29, 29)
BEER, BEER_DARK, FOAM, GLASS = (245, 166, 35), (214, 130, 12), (255, 252, 242), (255, 255, 255)


def u(v: float) -> int:
    """Koordinaten in 1024er-Einheiten -> Pixel der Zeichenfläche."""
    return round(v * S / 1024)


def box(x0, y0, x1, y1):
    return [u(x0), u(y0), u(x1), u(y1)]


def background(size: int) -> Image.Image:
    bg = Image.new("RGB", (1, 2))
    bg.putpixel((0, 0), BG_TOP)
    bg.putpixel((0, 1), BG_BOTTOM)
    return bg.resize((size, size), Image.BICUBIC)


def artwork() -> Image.Image:
    """Motiv auf transparentem Grund, 1024er-Raster, Mittelpunkt etwa (512, 512)."""
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = 470  # Pokal etwas nach links, Platz für den Krug

    # --- Pokal
    d.arc(box(cx - 262, 250, cx - 102, 470), 80, 280, fill=GOLD_DARK, width=u(38))  # Henkel links
    d.arc(box(cx + 102, 250, cx + 262, 470), 260, 100, fill=GOLD_DARK, width=u(38))  # Henkel rechts
    d.chord(box(cx - 205, -40, cx + 205, 590), 0, 180, fill=GOLD)  # Schale
    d.chord(box(cx - 205, -40, cx + 205, 590), 0, 180, outline=GOLD_DARK, width=u(10))
    d.rounded_rectangle(box(cx - 225, 252, cx + 225, 296), radius=u(20), fill=GOLD_LIGHT, outline=GOLD_DARK, width=u(8))
    d.polygon([(u(cx - 44), u(585)), (u(cx + 44), u(585)), (u(cx + 26), u(690)), (u(cx - 26), u(690))], fill=GOLD_DARK)
    d.rounded_rectangle(box(cx - 120, 680, cx + 120, 728), radius=u(14), fill=GOLD, outline=GOLD_DARK, width=u(8))
    d.rounded_rectangle(box(cx - 175, 722, cx + 175, 800), radius=u(18), fill=GOLD_DARK)

    # --- Dartscheibe auf der Schale
    bx, by = cx, 420
    for r, col in ((118, BLACK), (106, RED), (92, CREAM), (70, BOARD_GREEN), (56, CREAM), (32, RED), (15, BOARD_GREEN)):
        d.ellipse(box(bx - r, by - r, bx + r, by + r), fill=col)

    # --- Dart (steckt im Bull, kommt von rechts oben)
    tip = (bx + 6, by - 6)
    tail = (bx + 230, by - 230)
    d.line([(u(tip[0]), u(tip[1])), (u(tail[0]), u(tail[1]))], fill=(214, 220, 228), width=u(20))
    d.line([(u(tip[0] + 40), u(tip[1] - 40)), (u(tip[0] + 110), u(tip[1] - 110))], fill=(90, 98, 110), width=u(30))  # Griff
    fx, fy = tail
    d.polygon([(u(fx - 30), u(fy + 30)), (u(fx + 40), u(fy - 70)), (u(fx + 70), u(fy - 40))], fill=RED)  # Flight
    d.polygon([(u(fx - 30), u(fy + 30)), (u(fx + 60), u(fy + 10)), (u(fx + 20), u(fy - 30))], fill=(170, 30, 40))

    # --- Bierkrug rechts unten, mit dunklem Rand zur Abgrenzung
    mx0, my0, mx1, my1 = 640, 520, 820, 800
    d.rounded_rectangle(box(mx0 - 14, my0 - 14, mx1 + 14, my1 + 14), radius=u(40), fill=BG_BOTTOM)
    d.arc(box(mx1 - 50, my0 + 50, mx1 + 90, my1 - 60), 270, 90, fill=BG_BOTTOM, width=u(62))  # Henkel-Rand
    d.arc(box(mx1 - 50, my0 + 50, mx1 + 90, my1 - 60), 270, 90, fill=GLASS, width=u(30))  # Henkel
    d.rounded_rectangle(box(mx0, my0, mx1, my1), radius=u(30), fill=BEER)
    d.rectangle(box(mx0 + 30, my0 + 70, mx0 + 52, my1 - 30), fill=(255, 214, 120))  # Glanz
    for i in range(3):
        d.rectangle(box(mx0 + 90 + i * 34, my0 + 80, mx0 + 102 + i * 34, my1 - 30), fill=BEER_DARK)  # Rillen
    for (x, y, r) in ((mx0 + 30, my0, 46), (mx0 + 90, my0 - 22, 54), (mx0 + 150, my0 - 4, 48), (mx1 - 4, my0 + 10, 34)):
        d.ellipse(box(x - r, y - r, x + r, y + r), fill=FOAM)  # Schaum
    d.rectangle(box(mx0, my0, mx1, my0 + 30), fill=FOAM)
    return im


def render(size: int, scale: float) -> Image.Image:
    """scale = Anteil der Icon-Breite, den das Motiv einnimmt (maskable braucht Rand)."""
    art = artwork()
    bbox = art.getbbox()
    art = art.crop(bbox)
    target = round(size * 4 * scale)
    w, h = art.size
    f = target / max(w, h)
    art = art.resize((round(w * f), round(h * f)), Image.LANCZOS)
    canvas = background(size * 4).convert("RGBA")
    canvas.alpha_composite(art, ((size * 4 - art.width) // 2, (size * 4 - art.height) // 2))
    return canvas.convert("RGB").resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    render(512, 0.80).save(OUT / "icon-512.png", optimize=True)
    render(192, 0.80).save(OUT / "icon-192.png", optimize=True)
    render(180, 0.78).save(OUT / "apple-touch-icon.png", optimize=True)
    render(512, 0.62).save(OUT / "icon-maskable-512.png", optimize=True)  # sichere Zone für runde Masken
    render(128, 0.66).save(OUT / "logo-128.png", optimize=True)  # rundes Logo in der Kopfzeile
    print("Icons geschrieben nach", OUT)


if __name__ == "__main__":
    main()
