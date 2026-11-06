"""Прайс Masio (xlsx) → sources/masio.json + фото в assets/masio/.

Masio надсилає прайс таблицею; постійного фіду немає. Коли приходить новий прайс:
    python3 tools/masio_convert.py шлях/до/прайсу.xlsx
і закомітити sources/masio.json та assets/masio/.

Аркуш «Обідні столи»: блок починається з рядка з назвою (фото, форма, розкладний,
матеріал, ніжки, опції), наступні рядки — інші розміри того ж блоку. Ціна — МРРЦ.
"""
import hashlib
import io
import json
import os
import re
import sys

import openpyxl
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(ROOT, "assets", "masio")
RAW = "https://raw.githubusercontent.com/akordmebli/furniture-feed/main/assets/masio/"


def num(v):
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"\d+(?:[.,]\d+)?", str(v or ""))
    return float(m[0].replace(",", ".")) if m else 0.0


def main(path):
    wb = openpyxl.load_workbook(path)
    ws = wb["Обідні столи"]
    hdr_row = next(r for r in range(1, 10) if ws.cell(r, 2).value == "Назва товару")
    col = {str(ws.cell(hdr_row, c).value or "").strip(): c for c in range(1, ws.max_column + 1)}
    C = lambda name: col[name]  # noqa: E731
    images = {}
    for im in ws._images:
        images[im._from.row + 1 if hasattr(im, "_from") else im.anchor._from.row + 1] = im._data()
    os.makedirs(IMG_DIR, exist_ok=True)
    saved = {}
    blocks, cur = [], None
    for r in range(hdr_row + 1, ws.max_row + 1):
        name = ws.cell(r, C("Назва товару")).value
        size = ws.cell(r, C("Розмір (см.)")).value
        if not name and not size:
            continue
        if name:
            link = ws.cell(r, C("Сайт")).hyperlink
            cur = {
                "name": " ".join(str(name).split()),
                "form": str(ws.cell(r, C("Форма")).value or "").strip(),
                "ext": str(ws.cell(r, C("Розкладний")).value or "").strip().lower() == "так",
                "material": str(ws.cell(r, C("Матеріал")).value or "").strip(),
                "legs": str(ws.cell(r, C("Ніжки")).value or "").strip(),
                "notes": " ".join(str(ws.cell(r, C("Хар-ки")).value or "").split()).strip(" -"),
                "link": link.target if link else "",
                "image": "",
                "rows": [],
            }
            data = images.get(r)
            if data:
                h = hashlib.md5(data).hexdigest()[:10]
                if h not in saved:
                    im = Image.open(io.BytesIO(data)).convert("RGB")
                    im.thumbnail((2048, 2048))
                    fn = f"masio-{h}.jpg"
                    im.save(os.path.join(IMG_DIR, fn), "JPEG", quality=88)
                    saved[h] = RAW + fn
                cur["image"] = saved[h]
            blocks.append(cur)
        if cur is None:
            continue
        price = num(ws.cell(r, C("МРРЦ")).value)
        cur["rows"].append({
            "size": " ".join(str(size or "").split()),
            "sku": str(ws.cell(r, C("SKU")).value or "").replace(".0", ""),
            "price": price,
        })
    out = os.path.join(ROOT, "sources", "masio.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(blocks, f, ensure_ascii=False, indent=1)
    print(f"{len(blocks)} блоків, {sum(len(b['rows']) for b in blocks)} розмірів, {len(saved)} фото → {out}")


if __name__ == "__main__":
    main(sys.argv[1])
