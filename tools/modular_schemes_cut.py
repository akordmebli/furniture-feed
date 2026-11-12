"""Нарізка схем модульних диванів із техкаталогу «Кутові дивани_3.xlsx».
Кожен фрагмент — на біле полотно 4:3 (як фото товарів), з полями."""
import json, os, sys
from PIL import Image

MEDIA = sys.argv[1]          # .../xl/media
OUT = sys.argv[2]
os.makedirs(OUT, exist_ok=True)
W, H, PAD = 1600, 1200, 80

# (файл-результат, джерело, box або None = ціле зображення, alt)
JOBS = [
    # --- BELAMO: модулі (image13), сети (image6, 9, 8)
    ("belamo-modul-dk0", 13, (640, 62, 975, 282), "BELAMO ДК0 пуф (лівий/правий)"),
    ("belamo-modul-dk1", 13, (2, 288, 275, 507), "BELAMO ДК1 крокодил (ліва/права)"),
    ("belamo-modul-dk3", 13, (640, 288, 780, 470), "BELAMO ДК3 крісло приставне розкладне"),
    ("belamo-modul-dk5", 13, (4, 516, 268, 702), "BELAMO ДК5 крісло кутове розкладне (ліве/праве)"),
    ("belamo-set-1", 6, (5, 82, 515, 345), "BELAMO SET 1"),
    ("belamo-set-2", 6, (645, 82, 1065, 345), "BELAMO SET 2"),
    ("belamo-set-3", 6, (5, 445, 515, 705), "BELAMO SET 3"),
    ("belamo-set-4", 6, (645, 445, 1065, 705), "BELAMO SET 4"),
    ("belamo-set-5", 9, (5, 92, 490, 358), "BELAMO SET 5"),
    ("belamo-set-6", 9, (615, 92, 1025, 450), "BELAMO SET 6"),
    ("belamo-set-7", 9, (5, 455, 490, 742), "BELAMO SET 7"),
    ("belamo-set-8", 9, (615, 455, 1025, 742), "BELAMO SET 8"),
    ("belamo-set-9", 8, (10, 90, 370, 295), "BELAMO SET 9"),
    ("belamo-set-10", 8, (480, 90, 665, 295), "BELAMO SET 10"),
    ("belamo-set-11", 8, (748, 90, 1005, 295), "BELAMO SET 11"),
    # --- CASIO: модулі (image15), сети (image12, 11, 7)
    ("casio-modul-komplekt", 15, (20, 95, 382, 325), "CASIO комплект (отаманка + приставне + кутове крісло)"),
    ("casio-modul-kutove", 15, (878, 95, 1215, 303), "CASIO кутове крісло (з білом)"),
    ("casio-modul-otamanka", 15, (418, 95, 842, 388), "CASIO отаманка (з білом)"),
    ("casio-modul-prystavne", 15, (820, 408, 1133, 647), "CASIO приставне крісло"),
    ("casio-modul-puf", 15, (218, 665, 398, 840), "CASIO пуф"),
    ("casio-set-1", 12, (20, 110, 480, 430), "CASIO SET 1"),
    ("casio-set-2", 12, (785, 110, 1205, 430), "CASIO SET 2"),
    ("casio-set-3", 12, (20, 500, 465, 870), "CASIO SET 3"),
    ("casio-set-4", 12, (785, 500, 1160, 815), "CASIO SET 4"),
    ("casio-set-5", 11, (15, 45, 412, 295), "CASIO SET 5"),
    ("casio-set-6", 7, None, "CASIO SET 6"),
    ("casio-chair", 11, (15, 435, 250, 645), "CASIO CHAIR"),
    # --- RUBY: модулі + SET 1 (image37), сети 5–8 (image33)
    ("ruby-modul-dk0", 37, (476, 92, 897, 526), "RUBY ДК0 отоманка довга (ліва/права)"),
    ("ruby-modul-dk1", 37, (938, 92, 1360, 420), "RUBY ДК1 отоманка коротка (ліва/права)"),
    ("ruby-modul-dk2", 37, (25, 594, 486, 834), "RUBY ДК2 крісло кутове (ліве/праве)"),
    ("ruby-modul-dk3", 37, (489, 594, 690, 834), "RUBY ДК3 крісло приставне"),
    ("ruby-set-1", 37, (25, 92, 470, 418), "RUBY SET 1"),
    ("ruby-set-5", 33, (5, 5, 410, 295), "RUBY SET 5"),
    ("ruby-set-6", 33, (565, 5, 960, 245), "RUBY SET 6"),
    ("ruby-set-7", 33, (5, 310, 315, 495), "RUBY SET 7"),
    ("ruby-set-8", 33, (565, 310, 805, 500), "RUBY SET 8"),
    # --- SIENA: модулі (image30), сети 1–4 окремі (34, 35, 38, 36), 5–8 (39, 29)
    ("siena-modul-dk0", 30, (512, 106, 850, 466), "SIENA ДК0 отоманка довга (ліва/права)"),
    ("siena-modul-dk2", 30, (0, 535, 342, 755), "SIENA ДК2 крісло кутове (ліве/праве)"),
    ("siena-modul-dk3", 30, (390, 535, 556, 755), "SIENA ДК3 крісло приставне"),
    ("siena-set-1", 34, None, "SIENA SET 1"),
    ("siena-set-2", 35, None, "SIENA SET 2"),
    ("siena-set-3", 38, None, "SIENA SET 3"),
    ("siena-set-4", 36, None, "SIENA SET 4"),
    ("siena-set-5", 39, (35, 15, 715, 505), "SIENA SET 5"),
    ("siena-set-6", 29, (25, 0, 590, 490), "SIENA SET 6"),
    ("siena-set-7", 39, (35, 545, 600, 760), "SIENA SET 7"),
    ("siena-set-8", 29, (25, 525, 450, 735), "SIENA SET 8"),
]
# оглядові сторінки «Схеми та розміри» → поп-ап custom.scheme_image
OVERVIEW = {"belamo": 13, "casio": 15, "ruby": 37, "siena": 30}

manifest = []
for name, src, box, alt in JOBS:
    im = Image.open(f"{MEDIA}/image{src}.png").convert("RGBA")
    bg = Image.new("RGBA", im.size, "white"); bg.alpha_composite(im); im = bg.convert("RGB")
    if box:
        im = im.crop(box)
    k = min((W - 2 * PAD) / im.width, (H - 2 * PAD) / im.height, 5.0)
    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), "white")
    canvas.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
    fn = f"modulnyi-dyvan-{name}-skhema.png"
    canvas.save(f"{OUT}/{fn}", optimize=True)
    manifest.append({"file": fn, "model": name.split("-")[0], "alt": f"Схема з розмірами: {alt}",
                     "kind": "module" if "-modul-" in name else "set", "scale": round(k, 2)})
for model, src in OVERVIEW.items():
    im = Image.open(f"{MEDIA}/image{src}.png").convert("RGBA")
    bg = Image.new("RGBA", im.size, "white"); bg.alpha_composite(im)
    fn = f"modulnyi-dyvan-{model}-skhemy-ta-rozmiry.png"
    bg.convert("RGB").save(f"{OUT}/{fn}", optimize=True)
    manifest.append({"file": fn, "model": model, "alt": f"Схема з розмірами: {model.upper()} — модулі",
                     "kind": "overview", "scale": 1})
json.dump(manifest, open(f"{OUT}/manifest.json", "w"), ensure_ascii=False, indent=1)
print(len(manifest), "files")
