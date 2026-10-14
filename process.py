"""
Зведений фід товарів для Акорд Меблі → Shopify.

Джерела (URL у секретах GitHub):
  AKORD_CSV    — вигрузка ShopExpress (ВНД / VINADI), один рядок = один варіант
  VETRO_XML    — YML-фід Vetro Mebel (беремо ЛИШЕ українські поля name_ua / description_ua)
  COMEFOR_XML  — фід Come-For (ціна в <priceuah>, фото в <image>)
  WOODMAN_CSV  — таблиця Woodman (необов'язково; вмикається WOODMAN_ENABLED=1)

Категорії: кожен товар отримує product_type — назву кінцевої категорії з дерева магазину
(див. TREE). Автоматичні колекції в Shopify будуються саме за product_type.

Якщо будь-яке обов'язкове джерело не завантажилось або повернуло 0 товарів,
скрипт завершується з помилкою і НЕ перезаписує output/feed.xml —
щоб імпорт у Shopify не видалив товари через порожній фід.
"""
import csv
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from io import StringIO
from xml.dom import minidom

import requests

with open("mapping.json", encoding="utf-8") as f:
    MAPPING = json.load(f)

# Дерево категорій магазину: кінцева категорія → батьківська
TREE = {
    "Прямі дивани": "Дивани", "Кутові дивани": "Дивани", "Модульні дивани": "Дивани",
    "М'які крісла": "Крісла", "Обідні крісла": "Крісла",
    "Обідні стільці": "Стільці", "Барні стільці": "Стільці",
    "Обідні столи": "Столи", "Журнальні столики і консолі": "Столи",
    "М'які ліжка": "Ліжка", "Кутові ліжка": "Ліжка", "Дитячі ліжка": "Ліжка", "Каркаси ліжок": "Ліжка",
    "Пуфи": "Пуфи та лавки", "Лавки": "Пуфи та лавки",
    "Тумбочки": "Тумби та зберігання", "Буфети і ТВ-тумби": "Тумби та зберігання",
    "Безпружинні матраци": "Матраци та аксесуари для сну", "Наматрасники": "Матраци та аксесуари для сну",
    "Подушки": "Матраци та аксесуари для сну", "Ковдри": "Матраци та аксесуари для сну",
    "Садові меблі": "Садові меблі",
    "Меблі для закладів": "Меблі для закладів",
}

SHOPIFY_TAXONOMY = {
    "Прямі дивани": "fr-22", "Кутові дивани": "fr-22-3", "Модульні дивани": "fr-22-6",
    "М'які крісла": "fr-7-1", "Обідні крісла": "fr-7-9",
    "Обідні стільці": "fr-7-9", "Барні стільці": "fr-7-12",
    "Обідні столи": "fr-24-4", "Журнальні столики і консолі": "fr-24-1",
    "М'які ліжка": "fr-2-2", "Кутові ліжка": "fr-2-2", "Дитячі ліжка": "fr-1-6", "Каркаси ліжок": "fr-2-2",
    "Пуфи": "fr-14", "Лавки": "fr-3", "Тумбочки": "fr-24-6", "Буфети і ТВ-тумби": "fr-24-6",
    "Безпружинні матраци": "fr-2-6", "Наматрасники": "hg-15-1-12", "Подушки": "hg-15-1-9",
    "Ковдри": "hg-15-1-4", "Садові меблі": "fr-15-2", "Меблі для закладів": "fr-22",
}

OPT_TAGS = ['fabric', 'leg_color', 'frame_color', 'sleep_size', 'mechanism',
            'pillows', 'back_fabric', 'mattress_included', 'material',
            'modules', 'dimensions', 'tabletop_size',
            'height_opt', 'length_opt', 'width_opt']

UNMAPPED = []


# ---------- утиліти ----------

def fetch_text(url):
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def clean_price(val):
    try:
        cleaned = str(val).replace(",", "").replace(" ", "").replace("\xa0", "").strip()
        return f"{float(cleaned):.2f}" if cleaned else "0.00"
    except (ValueError, TypeError):
        return "0.00"


def clean_text(s):
    """Прибирає залишки CDATA (']]>') і зайві пробіли."""
    s = str(s or "").replace("<![CDATA[", "").replace("]]>", "")
    return s.strip()


def map_leaf(source, key, title=""):
    leaf = MAPPING.get(source, {}).get(str(key).strip())
    if leaf not in TREE:
        UNMAPPED.append(f"{source}: {key!r} ({title})")
        return ""
    return leaf


def sleep_norm(v):
    """'1500*1900', '140*200', '160x200' → '150×190' / '140×200' / '160×200' (см)."""
    m = re.fullmatch(r"\s*(\d+)\s*[*xх×]\s*(\d+)\s*", str(v or ""))
    if not m:
        return ""
    a, b = int(m[1]), int(m[2])
    a = round(a / 10) if a >= 400 else a
    b = round(b / 10) if b >= 400 else b
    return f"{a}×{b}"


def cm(v):
    """Число в см; значення ≥400 вважаються міліметрами."""
    try:
        x = float(str(v).replace(",", ".").strip())
    except (ValueError, TypeError):
        return ""
    if x <= 0:
        return ""
    return str(round(x / 10) if x >= 400 else round(x))


def title_overrides(title, leaf):
    t = title.lower()
    if t.startswith("модульний диван"):
        return "Модульні дивани"
    if "буфет" in t or "тв-тумба" in t:
        return "Буфети і ТВ-тумби"
    if "шезлонг" in t or "садов" in t:
        return "Садові меблі"
    if "барний стілець" in t or t.startswith("барний"):
        return "Барні стільці"
    if "безкаркасн" in t and ("диван" in t or "софа" in t):
        return "Модульні дивани"
    if "безкаркасне крісло" in t or "поворотне крісло" in t:
        return "М'які крісла"
    if t.startswith("стілець") and leaf in ("Обідні крісла", ""):
        return "Обідні стільці"
    if t.startswith("комплект журнальних"):
        return "Журнальні столики і консолі"
    return leaf


def product(**kw):
    base = {
        "source": "", "sku": "", "handle": "", "name": "", "price": "0.00",
        "product_type": "", "images": [], "description": "", "available": True,
        "vendor": "", "instock": "", "barcode": "", "meta_title": "",
        "meta_description": "", "meta_keywords": "", "opts": {}, "tags": [],
        "sleep": "", "length": "", "width": "", "height": "",
    }
    base.update(kw)
    pt = base["product_type"]
    base["parent_category"] = TREE.get(pt, "")
    base["shopify_category"] = SHOPIFY_TAXONOMY.get(pt, "fr")
    # Довжина — завжди більша сторона
    if base["length"] and base["width"] and int(base["width"]) > int(base["length"]):
        base["length"], base["width"] = base["width"], base["length"]
    return base


# ---------- джерела ----------

def parse_akord(text):
    products = []
    reader = csv.DictReader(StringIO(text))
    print('AKORD columns:', reader.fieldnames)
    seen = set()
    for row in reader:
        sku = str(row.get("Sku", "") or "").strip()
        opts = {}
        for tag in OPT_TAGS:
            val = str(row.get(tag, "") or "").strip()
            if val and val.lower() != "nan":
                opts[tag] = val
        # один SKU може стояти на кількох варіантах — ключ = SKU + опції
        key = (sku, tuple(sorted(opts.items())), row.get("Alias", ""))
        if key in seen:
            continue
        seen.add(key)

        name = clean_text(row.get("Name", ""))
        cat = str(row.get("category", "") or "").strip()
        leaf = map_leaf("akord", cat.split(" / ")[-1] if cat else "", name)
        leaf = title_overrides(name, leaf)
        tags = []
        if "нерозкладн" in cat.lower() or "нерозкладн" in (row.get("ShortDescription", "") or "").lower():
            tags.append("нерозкладний")

        images_raw = row.get("image", "") or row.get("variant_image", "") or row.get("Images", "") or ""
        images = [i.strip() for i in images_raw.split(",") if i.strip()]

        products.append(product(
            source="akord", sku=sku, handle=str(row.get("Alias", "") or ""),
            name=name,
            price=clean_price(row.get("price", "") or row.get("variant_price", "") or row.get("Price", "")),
            product_type=leaf, images=images,
            description=clean_text(row.get("ShortDescription", "")),
            available=str(row.get("IsAvailable", "")).strip() == "Available",
            vendor="ВНД", instock=str(row.get("InStock", "") or ""),
            barcode=str(row.get("Barcode", "") or ""),
            meta_title=str(row.get("MetaTitle", "") or ""),
            meta_description=str(row.get("MetaDescription", "") or ""),
            meta_keywords=str(row.get("MetaKeywords", "") or ""),
            opts=opts, tags=tags, sleep=sleep_norm(opts.get("sleep_size", "")),
            length=cm(opts.get("length_opt", "")), width=cm(opts.get("width_opt", "")),
            height=cm(opts.get("height_opt", "")),
        ))
    return products


def vetro_param(params, *names):
    for n in names:
        if params.get(n):
            return cm(params[n])
    return ""


def parse_vetro(text):
    products = []
    root = ET.fromstring(text.encode("utf-8"))
    for offer in root.find("shop").find("offers"):
        name = clean_text(offer.findtext("name_ua", ""))
        if not name:  # без української назви товар не публікуємо
            continue
        params = {p.get("name"): (p.text or "").strip() for p in offer.findall("param")}
        cat_id = offer.findtext("categoryId", "").strip()
        leaf = title_overrides(name, map_leaf("vetro", cat_id, name))
        diam = vetro_param(params, "Діаметр, см")
        products.append(product(
            source="vetro",
            sku=offer.findtext("article", "") or offer.findtext("vendorCode", "") or offer.get("id", ""),
            handle="vetro-" + offer.get("id", ""),
            name=name,
            price=clean_price(offer.findtext("price", "")),
            product_type=leaf,
            images=[p.text.strip() for p in offer.findall("picture") if p.text],
            description=clean_text(offer.findtext("description_ua", "")),
            available=offer.get("available") == "true",
            vendor="Vetro Mebel",
            instock=offer.findtext("stock_quantity", "") or "",
            length=vetro_param(params, "Довжина, см", "Максимальна довжина стільниці, см", "Ширина дивану, см") or diam,
            width=vetro_param(params, "Ширина, см", "Ширина сидіння, см") or diam,
            height=vetro_param(params, "Висота, см", "Висота крісла, см", "Висота дивану, см"),
        ))
    return products


def first_text(item, *tags):
    """Перший непорожній дочірній тег (без урахування регістру) — у фідах бувають опечатки на кшталт priceRUAH."""
    low = {c.tag.lower(): (c.text or "").strip() for c in item}
    for t in tags:
        if low.get(t.lower()):
            return low[t.lower()]
    return ""


def parse_comefor(text):
    products = []
    root = ET.fromstring(text.encode("utf-8"))
    items = root.find("items")
    _first = next(iter(items if items is not None else root.iter("item")), None)
    if _first is not None:
        print("COMEFOR first item:", ET.tostring(_first, encoding="unicode")[:1800].replace("\n", " "))
    print("COMEFOR categories:", [(c.findtext("id"), c.findtext("parentId"), c.findtext("name")) for c in root.iter("category")][:60])
    for item in (items if items is not None else root.iter("item")):
        name = clean_text(item.findtext("name", ""))
        cat_id = item.findtext("categoryId", "").strip()
        if MAPPING["comefor"].get(cat_id) == "SKIP":
            continue
        leaf = map_leaf("comefor", cat_id, name)
        t = name.lower()
        if "наматрацник" in t or "підматрацник" in t:
            leaf = "Наматрасники"
        params = {(p.get("name") or "").strip(): (p.text or "").strip() for p in item.findall("param")}
        height = ""
        for k, v in params.items():
            if k.lower().startswith("висота"):
                m = re.search(r"(\d+(?:[.,]\d+)?)\s*(см|мм)?", v)
                if m:
                    x = float(m[1].replace(",", "."))
                    height = str(round(x / 10 if m[2] == "мм" else x))
                    break
        size = re.search(r"(\d{2,3})\s*[xхX×]\s*(\d{2,3})\b", name)
        if not size:  # подушки: розмір лише в параметрі «Розмір»
            size = re.search(r"(\d{2,3})\s*[xхX×]\s*(\d{2,3})", params.get("Розмір", ""))
        imgs = []
        for e in item.findall("image") + item.findall("picture"):
            if e.text and e.text.strip() not in imgs:
                imgs.append(e.text.strip())
        products.append(product(
            source="comefor", sku=first_text(item, "code", "sku"),
            handle="comefor-" + (item.findtext("id", "") or first_text(item, "code", "sku")),
            name=name, price=clean_price(first_text(item, "priceuah", "priceruah", "price") or "0"),
            product_type=leaf, images=imgs,
            description=clean_text(html.unescape(item.findtext("description", "") or "")),
            available=item.findtext("stock", "").strip() in ("В наличии", "В наявності"),
            vendor="Come-For",
            sleep=f"{size[1]}×{size[2]}" if size else "",
            width=min(size[1], size[2], key=int) if size else "",
            length=max(size[1], size[2], key=int) if size else "",
            height=height,
        ))
    return products


def parse_woodman(text):
    """Перший рядок — українські заголовки, другий — технічні англійські ключі."""
    rows = list(csv.reader(StringIO(text)))
    if len(rows) < 3:
        return []
    ua, keys = rows[0], rows[1]
    products = []
    for r in rows[2:]:
        row = {}
        for i, v in enumerate(r):
            k = keys[i] if i < len(keys) and keys[i] else (ua[i] if i < len(ua) else "")
            row.setdefault(k, v)
        uarow = {ua[i]: v for i, v in enumerate(r) if i < len(ua)}
        name = clean_text(row.get("name", ""))
        if not name:
            continue
        cat = (uarow.get("КАТЕГОРІЯ", "") or "").strip().lower()
        leaf = title_overrides(name, map_leaf("woodman", cat, name))
        img = (row.get("image_1", "") or row.get("photo", "")).strip()
        products.append(product(
            source="woodman", sku=row.get("sku", ""), handle="woodman-" + row.get("sku", "").lower(),
            name=name, price=clean_price(row.get("rrp_price", "")),
            product_type=leaf, images=[img] if img.startswith("http") else [],
            description=clean_text(row.get("description", "")),
            vendor="Woodman", barcode=row.get("ean", ""),
            length=cm(uarow.get("ДОВЖИНА, см", "")), width=cm(uarow.get("ШИРИНА, см", "")),
            height=cm(uarow.get("ВИСОТА, см", "")),
        ))
    return products



# ---------- групування у варіанти ----------

SIZE_RE = re.compile(r"\s*(\d{2,3})\s*[xхXХ×*]\s*(\d{2,3})(?:\s*(?:см|cm))?(?=\s|,|$)")
FRAME_RE = re.compile(r"\s*((?:[а-яіїєґ'’]+ кольору)|без покриття|карамель)\s*$", re.I)
CODE_RE = re.compile(r"^(.*?\b[A-ZА-Я]{1,4}[- ]?\d[\w\-./]*)\s*(.*)$")
QUOTE_RE = re.compile(r'^(.*?"[^"]+")\s*(.*)$')


TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie", "ж": "zh",
    "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ю": "iu", "я": "ia", "ь": "", "'": "", "’": "",
}


def slug(s):
    out = "".join(TRANSLIT.get(ch, ch) for ch in s.lower())
    return re.sub(r"[^a-z0-9]+", "-", out).strip("-")


def split_comefor(p):
    m = re.search(r"\s*(\d{2,3})\s*[xхX×]\s*(\d{2,3})\b", p["name"])
    if not m:
        return p["name"], {}
    base = (p["name"][:m.start()] + p["name"][m.end():]).strip()
    return base, {"Розмір": f"{m[1]}×{m[2]}"}


def split_vetro(p):
    n = p["name"]
    m = QUOTE_RE.match(n) or CODE_RE.match(n)
    if not m or not m[2].strip():
        return n, {}
    return m[1].strip(), {"Колір": m[2].strip()}


def split_woodman(p):
    n = p["name"]
    opts = {}
    if ", " in n:
        n, fabric = n.rsplit(", ", 1)
        opts["Колір тканини"] = fabric.strip()
    sz = SIZE_RE.search(n)
    if sz:
        opts["Розмір"] = f"{sz[1]}×{sz[2]}"
        n = (n[:sz.start()] + n[sz.end():]).strip()
    fm = FRAME_RE.search(n)
    if fm:
        opts["Колір каркаса"] = fm[1].strip()
        n = n[:fm.start()].strip()
    return n, opts


SPLITTERS = {"comefor": split_comefor, "vetro": split_vetro, "woodman": split_woodman}
OPTION_ORDER = ["Розмір", "Колір каркаса", "Колір тканини", "Колір"]


def group_variants(products):
    """Об'єднує постачальницькі позиції в один товар з варіантами.
    Фід лишається плоским (один <item> = один варіант), спільний handle групує варіанти."""
    out, groups = [], {}
    for p in products:
        sp = SPLITTERS.get(p["source"])
        if not sp:
            out.append(p)
            continue
        base, opts = sp(p)
        key = (p["source"], p["product_type"], base)
        p["group_name"], p["group_opts"] = base, opts
        groups.setdefault(key, []).append(p)
    for (src, ptype, base), items in groups.items():
        # розмір — як опція, якщо габарити відрізняються всередині групи
        if len(items) > 1 and not all("Розмір" in i["group_opts"] for i in items):
            dims = {(i["length"], i["width"]) for i in items}
            if len(dims) > 1 and all(i["length"] and i["width"] for i in items):
                for i in items:
                    i["group_opts"] = {"Розмір": f'{i["width"]}×{i["length"]}', **i["group_opts"]}
        names = [n for n in OPTION_ORDER if any(n in i["group_opts"] for i in items)]
        names = [n for n in names if len({i["group_opts"].get(n, "—") for i in items}) > 1][:3]
        # однакові комбінації опцій не можна — тоді не групуємо, щоб нічого не загубити
        combos = [tuple(i["group_opts"].get(n, "—") for n in names) for i in items]
        handle = f"{src}-{slug(base)}"[:120]
        if len(items) == 1 or not names or len(set(combos)) != len(items):
            for i in items:
                i["option_names"], i["option_values"] = [], []
                i["handle"] = handle if len(items) == 1 else i["handle"]
                if len(items) > 1:
                    i["group_name"] = i["name"]
                out.append(i)
            continue
        for i, c in zip(items, combos):
            i["handle"] = handle
            i["name"] = base
            i["option_names"], i["option_values"] = names, list(c)
            out.append(i)
    seen = set()
    for p in out:  # SKU у фіді постачальника інколи дублюється — робимо унікальним
        if p["sku"] in seen:
            suffix = "-".join(p.get("option_values") or []) or p["handle"]
            p["sku"] = f'{p["sku"]}-{slug(suffix)}'
        seen.add(p["sku"])
    return out


# ---------- вивід ----------

def build_xml(products):
    catalog = ET.Element("catalog")
    for p in products:
        item = ET.SubElement(catalog, "item")
        fields = [
            ("sku", p["sku"]), ("handle", p["handle"]), ("name", p["name"]),
            ("variant_price", p["price"]), ("vendor", p["vendor"]),
            ("product_type", p["product_type"]),
            ("category", p["product_type"]),              # зворотна сумісність
            ("parent_category", p["parent_category"]),
            ("shopify_id", p["shopify_category"]),
            ("tags", ", ".join(p["tags"])),
            ("available", "true" if p["available"] else "false"),
            ("instock", p["instock"]), ("barcode", p["barcode"]),
            ("meta_title", p["meta_title"]), ("meta_description", p["meta_description"]),
            ("meta_keywords", p["meta_keywords"]), ("alias", p["handle"]),
            ("description", p["description"]),
            ("spalne_mistse", p["sleep"]), ("dovzhyna", p["length"]),
            ("shyryna", p["width"]), ("vysota", p["height"]),
        ]
        for tag, val in fields:
            ET.SubElement(item, tag).text = str(val or "")
        for tag in OPT_TAGS:
            ET.SubElement(item, tag).text = str(p["opts"].get(tag, "") or "")
        names, vals = p.get("option_names", []), p.get("option_values", [])
        for n in range(3):
            ET.SubElement(item, f"option{n + 1}_name").text = names[n] if n < len(names) else ""
            ET.SubElement(item, f"option{n + 1}_value").text = vals[n] if n < len(vals) else ""
        ET.SubElement(item, "variant_image").text = p["images"][0] if p["images"] else ""
        images_el = ET.SubElement(item, "images")
        for img in p["images"]:
            ET.SubElement(images_el, "image").text = img
    raw = ET.tostring(catalog, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def main():
    sources = [
        ("Акорд (ВНД)", "AKORD_CSV", parse_akord, True),
        ("Vetro", "VETRO_XML", parse_vetro, True),
        ("Come-For", "COMEFOR_XML", parse_comefor, True),
        ("Woodman", "WOODMAN_CSV", parse_woodman, os.environ.get("WOODMAN_ENABLED", "1") == "1"),
    ]
    all_products, failed = [], []
    for label, env, parser, enabled in sources:
        if not enabled:
            print(f"{label}: вимкнено")
            continue
        try:
            items = parser(fetch_text(os.environ[env]))
        except Exception as e:  # noqa: BLE001
            print(f"{label}: ПОМИЛКА — {e}")
            failed.append(label)
            continue
        if not items:
            print(f"{label}: 0 товарів")
            failed.append(label)
            continue
        no_price = sum(1 for p in items if float(p["price"]) <= 0)
        no_img = sum(1 for p in items if not p["images"])
        no_type = sum(1 for p in items if not p["product_type"])
        print(f"{label}: {len(items)} | без ціни {no_price} | без фото {no_img} | без категорії {no_type}")
        all_products += items

    if UNMAPPED:
        with open("unmapped.log", "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(set(UNMAPPED))))
        print(f"Нерозпізнані категорії: {len(set(UNMAPPED))} (див. unmapped.log)")
        print("UNMAPPED sample:", sorted(set(UNMAPPED))[:15])

    if failed:
        print(f"\nФід НЕ оновлено: не вдалося завантажити {', '.join(failed)}")
        sys.exit(1)

    all_products = group_variants(all_products)
    os.makedirs("output", exist_ok=True)
    with open("output/feed.xml", "w", encoding="utf-8") as f:
        f.write(build_xml(all_products))
    print(f"\nГотово: {len(all_products)} позицій → output/feed.xml")


if __name__ == "__main__":
    main()
