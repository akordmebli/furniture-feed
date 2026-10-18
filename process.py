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
    "Безпружинні матраци": "Матраци та аксесуари для сну", "Матраци": "Матраци та аксесуари для сну", "Наматрасники": "Матраци та аксесуари для сну",
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
    "Безпружинні матраци": "fr-2-6", "Матраци": "fr-2-6", "Наматрасники": "hg-15-1-12", "Подушки": "hg-15-1-9",
    "Ковдри": "hg-15-1-4", "Садові меблі": "fr-15-2", "Меблі для закладів": "fr-22",
}

OPT_TAGS = ['fabric', 'leg_color', 'frame_color', 'sleep_size', 'mechanism',
            'pillows', 'back_fabric', 'mattress_included', 'material',
            'modules', 'dimensions', 'tabletop_size',
            'height_opt', 'length_opt', 'width_opt', 'corner_side', 'armrests', 'seats', 'tabletop_color', 'boxes', 'storage_niche']

UNMAPPED = []


# ---------- утиліти ----------

def fetch_text(url):
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def clean_price(val):
    try:
        cleaned = str(val).replace(" ", "").replace("\xa0", "").strip()
        if re.fullmatch(r"\d+,\d{1,2}", cleaned):  # 25482,6 — десяткова кома (ВНД)
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
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
    if "крісло офісне" in t or "офісне крісло" in t:
        return "М'які крісла"
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

def brand_fix(text):
    """Магазин завжди пишемо «АКОРД МЕБЛІ». ВНД / VINADI — два різні бренди, не чіпаємо."""
    return re.sub(r"(?i)акорд меблі", "АКОРД МЕБЛІ", text or "")


# У вигрузці частину рядків QUEST скопійовано з Лоренс (чужий alias і фото): (alias, назва) -> правильний alias
ALIAS_FIXES = {
    ("stilets-lorens", "Стілець QUEST"): "stilets-quest",
    ("divan-monako", "Диван Прованс"): "divan-provans",  # це варіанти довжини 124 дивана Прованс
    ("myake-lizhko-tahta-EVERLAY", "Кутове ліжко EVERLAY"): "kutove-lizhko-everlay",
    ("myake-lizhko-tahta-everlay", "Кутове ліжко EVERLAY"): "kutove-lizhko-everlay",
}

# Нерозкладні дивани: у вигрузці стоїть «спальне місце», якого немає
NO_SLEEP_ALIASES = {"divan-bloom"}

VALUE_FIXES = {"mechanism": {"Крокуючий": "Покроковий"}}


def norm_size_value(tag, val):
    """Розміри в одному форматі: см (1500*1900 → 150*190), тумба — «80х120»."""
    val = VALUE_FIXES.get(tag, {}).get(val, val)
    if tag == "sleep_size":
        m = re.fullmatch(r"(\d+)\s*[*xхX×]\s*(\d+)", val)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a >= 1000 and b >= 1000:
                a, b = round(a / 10), round(b / 10)
            return f"{a}*{b}"
    if tag == "tabletop_size":
        return val.replace("x", "х").replace("X", "х")
    return val


FABRIC_ORDER = {"А": 0, "Б": 1, "В": 2, "Г": 3, "Д": 4, "Е": 5, "Ж": 6, "З": 7}


def natural_key(tag, val):
    if val == "Стандартна":
        return (0, -1, "")
    if tag == "fabric" and val in FABRIC_ORDER:
        return (0, FABRIC_ORDER[val], "")
    nums = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", val)]
    if nums:
        return (1, tuple(nums), val.lower())
    return (2, (), val.lower())


# Фото JORD зі сторінки товару на сайті (у вигрузці там фото ROSET)
JORD_IMAGES = [
    "https://akordmebli.com.ua/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/Jord.jpg",
    "https://akordmebli.com.ua/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/Jord-6.jpg",
    "https://akordmebli.com.ua/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/Jord-1.jpg",
    "https://akordmebli.com.ua/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/Jord-2.jpg",
    "https://akordmebli.com.ua/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/Jord-5.jpg",
    "https://akordmebli.com.ua/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/Jord-3.jpg",
    "https://akordmebli.com.ua/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/Jord-4.jpg",
    "https://akordmebli.com.ua/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/_imports/Media/shop-14308/Jord-7.jpg",
]

def clean_images(raw):
    """Лише справжні файли: без порожніх папок, подвійних слешів і з кодуванням пробілів/дужок."""
    from urllib.parse import quote
    out = []
    for u in (raw or "").split(","):
        u = u.strip()
        if not u or u.endswith("/"):
            continue
        u = re.sub(r"(?<!:)//+", "/", u)
        u = quote(u, safe=":/%")
        if u not in out:
            out.append(u)
    return out


def parse_akord(text):
    products = []
    reader = csv.DictReader(StringIO(text))
    print('AKORD columns:', reader.fieldnames)
    rows = list(reader)
    # рядок без фото бере фото зі «своїх» рядків з тим самим alias (Монако: фото стоять біля рядків Прованс)
    first_img = {}
    for row in rows:
        im = row.get("image", "") or row.get("variant_image", "") or row.get("Images", "") or ""
        if clean_images(im):
            first_img.setdefault(str(row.get("Alias", "") or ""), im)
    for row in rows:
        if not clean_images(row.get("image", "") or row.get("variant_image", "") or row.get("Images", "") or ""):
            row["image"] = first_img.get(str(row.get("Alias", "") or ""), "")
    fixed_images = {}
    for row in rows:
        a = str(row.get("Alias", "") or "")
        for (bad, nm), good in ALIAS_FIXES.items():
            if a == good and not fixed_images.get(good):
                fixed_images[good] = row.get("image", "") or row.get("variant_image", "") or row.get("Images", "") or ""
    for row in rows:
        fix = ALIAS_FIXES.get((str(row.get("Alias", "") or ""), clean_text(row.get("Name", ""))))
        if fix:
            row["Alias"] = fix
            if fixed_images.get(fix):
                row["image"] = fixed_images[fix]
    # в таблиці різні товари інколи мають однаковий Alias (скопійований рядок) —
    # перша назва лишає alias, інші отримують власний handle
    alias_owner = {}
    for row in rows:
        alias_owner.setdefault(str(row.get("Alias", "") or ""), clean_text(row.get("Name", "")))
    seen = set()
    for row in rows:
        sku = str(row.get("Sku", "") or "").strip()
        opts = {}
        for tag in OPT_TAGS:
            val = str(row.get(tag, "") or "").strip()
            if val and val.lower() != "nan":
                opts[tag] = norm_size_value(tag, val)
        no_sleep = str(row.get("Alias", "") or "") in NO_SLEEP_ALIASES
        if no_sleep:
            opts.pop("sleep_size", None)
        # один SKU може стояти на кількох варіантах — ключ = SKU + опції
        name = clean_text(row.get("Name", ""))
        alias = str(row.get("Alias", "") or "")
        if alias and alias_owner.get(alias) != name:
            alias = f"{alias}-{slug(name)}"
        key = (sku, tuple(sorted(opts.items())), alias)
        if key in seen:
            continue
        seen.add(key)

        cat = str(row.get("category", "") or "").strip()
        # кілька категорій через « | »: перша — основна (product_type), решта — теги з назвою категорії
        cats = [c.strip() for c in cat.split("|") if c.strip()]
        cat = cats[0] if cats else ""
        leaf = map_leaf("akord", cat.split(" / ")[-1] if cat else "", name)
        leaf = title_overrides(name, leaf)
        tags = []
        for extra in cats[1:]:
            t = extra.split(" / ")[-1]
            if t and t != leaf and t not in tags:
                tags.append(t)
        if "нерозкладн" in cat.lower() or "нерозкладн" in (row.get("ShortDescription", "") or "").lower():
            tags.append("нерозкладний")
        if no_sleep and "нерозкладний" not in tags:
            tags.append("нерозкладний")

        images_raw = row.get("image", "") or row.get("variant_image", "") or row.get("Images", "") or ""
        images = clean_images(images_raw)
        if "JORD" in name.upper() and "ROSET" in images_raw.upper():
            images = list(JORD_IMAGES)  # у вигрузці JORD містить фото ROSET — беремо власні

        products.append(product(
            source="akord", sku=sku, handle=alias,
            name=name,
            price=clean_price(row.get("price", "") or row.get("variant_price", "") or row.get("Price", "")),
            product_type=leaf, images=images,
            description=brand_fix(clean_text(row.get("ShortDescription", ""))),
            available=str(row.get("IsAvailable", "")).strip() == "Available",
            vendor="ВНД", instock=str(row.get("InStock", "") or ""),
            barcode=str(row.get("Barcode", "") or ""),
            meta_title=brand_fix(str(row.get("MetaTitle", "") or "")),
            meta_description=brand_fix(str(row.get("MetaDescription", "") or "")),
            meta_keywords=brand_fix(str(row.get("MetaKeywords", "") or "")),
            opts=opts, tags=tags, sleep=sleep_norm(opts.get("sleep_size", "")),
            length=cm(opts.get("length_opt", "")), width=cm(opts.get("width_opt", "")),
            height=cm(opts.get("height_opt", "")),
            dims_tab=str(row.get("dims_tab", "") or row.get("dimensions", "") or "").strip(),
            category_full=cat,
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
            available=comefor_available(item.findtext("stock", "")),
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



AKORD_OPT_LABELS = {
    "sleep_size": "Спальне місце", "fabric": "Категорія тканини", "tabletop_size": "Розмір стільниці",
    "mattress_included": "Матрац", "back_fabric": "Тканина спинки", "modules": "Модулі",
    "dimensions": "Розміри", "leg_color": "Колір ніжок", "frame_color": "Колір каркаса",
    "mechanism": "Механізм", "pillows": "Подушки", "material": "Матеріал",
    "length_opt": "Довжина", "width_opt": "Ширина", "height_opt": "Висота",
    "corner_side": "Сторона кута", "tabletop_color": "Колір стільниці", "armrests": "Підлокітники", "seats": "Кількість місць",
    "boxes": "Короби", "storage_niche": "Ніша для речей",
}
# Характеристики, що впливають на ціну (за порядком пріоритету). Решта — лише метафілди,
# і в опції потрапляють тільки якщо інакше варіанти збігаються (щоб не було дублікатів).
AKORD_PRICE_OPTS = ["sleep_size", "fabric", "tabletop_size", "mattress_included", "boxes", "back_fabric", "modules"]


def _akord_apply(items, tags):
    head, tail = tags[:2], tags[2:]
    cols = [[t] for t in head] + ([tail] if tail else [])
    names = [" і ".join(AKORD_OPT_LABELS[t] for t in g) for g in cols]
    # кома в значенні опції розбиває його на два варіанти під час імпорту -> «1,5» стає «1.5»
    vals = [[(" / ".join(i["opts"].get(t, "") for t in g if i["opts"].get(t, "")) or "—").replace(",", ".") for g in cols] for i in items]
    return names, vals


def akord_options(items):
    """Опції варіантів ВНД: цінові характеристики, що відрізняються всередині товару (handle)."""
    def varies(t):
        return len({i["opts"].get(t, "") for i in items}) > 1
    tags = [t for t in AKORD_PRICE_OPTS if varies(t)]
    names, vals = _akord_apply(items, tags) if tags else ([], [[] for _ in items])
    if len({tuple(v) for v in vals}) != len(items):  # цінових замало для унікальності
        tags += [t for t in AKORD_OPT_LABELS if t not in AKORD_PRICE_OPTS and varies(t)]
        names, vals = _akord_apply(items, tags)
    for i, v in zip(items, vals):
        i["option_names"], i["option_values"] = (names if tags else []), v


def group_variants(products):
    """Об'єднує постачальницькі позиції в один товар з варіантами.
    Фід лишається плоским (один <item> = один варіант), спільний handle групує варіанти."""
    out, groups, akord = [], {}, {}
    for p in products:
        sp = SPLITTERS.get(p["source"])
        if p["source"] == "akord":
            akord.setdefault(p["handle"], []).append(p)
            out.append(p)
            continue
        if not sp:
            out.append(p)
            continue
        p["name"] = " ".join(p["name"].split())  # подвійні пробіли ламали групування
        base, opts = sp(p)
        base = " ".join(base.split())
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
        if len(items) == 1 and items[0]["group_opts"]:
            # єдиний варіант: чиста назва моделі + опція (інші кольори з'являться в тому ж товарі сам)
            i = items[0]
            keys = [n for n in OPTION_ORDER if n in i["group_opts"]][:3]
            i["handle"], i["name"] = handle, base
            i["option_names"], i["option_values"] = keys, [i["group_opts"][k] for k in keys]
            out.append(i)
            continue
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
    for items in akord.values():
        akord_options(items)
        tab = build_tab_characteristics(items)
        for i in items:
            i["tab_characteristics"] = tab
            i["tab_materials"] = build_tab_materials(items)
    # варіанти від меншого до більшого: розмір, категорія тканини (А→Ж) та інші цінові опції
    order = {h: n for n, h in enumerate(akord)}
    sort_tags = AKORD_PRICE_OPTS + [t for t in AKORD_OPT_LABELS if t not in AKORD_PRICE_OPTS]
    key = lambda p: (order[p["handle"]], [natural_key(t, p["opts"].get(t, "")) for t in sort_tags])
    out = [p for p in out if p["source"] != "akord"] + sorted((p for p in out if p["source"] == "akord"), key=key)
    seen = set()
    for p in out:  # SKU у фіді постачальника інколи дублюється — робимо унікальним
        if p["sku"] in seen:
            suffix = "-".join(p.get("option_values") or []) or p["handle"]
            p["sku"] = f'{p["sku"]}-{slug(suffix)}'
        seen.add(p["sku"])
    return out


# ---------- вкладки картки товару (rich-text метаполя) ----------
def _rt(lines):
    """lines: [(підпис, значення)] -> JSON rich text Shopify (маркований список)."""
    items = [{"type": "list-item", "children": [
        {"type": "text", "value": f"{k}: ", "bold": True}, {"type": "text", "value": v}]} for k, v in lines if v]
    if not items:
        return ""
    return json.dumps({"type": "root", "children": [{"type": "list", "listType": "unordered", "children": items}]},
                      ensure_ascii=False, separators=(",", ":"))


def _dims_text(d):
    parts = [x.strip() for x in d.replace("×", "*").replace("x", "*").split("*") if x.strip()]
    return "×".join(parts) + " см" if parts else ""


def _sleep_text(v):
    return v.replace("*", "×").replace("x", "×") + " см"


def build_tab_characteristics(items):
    p0 = items[0]
    cat = (p0.get("category_full", "") + " " + p0["name"]).lower()
    is_chair = "крісла" in cat or "стільці" in cat
    axes = ["Ширина", "Глибина", "Висота"] if is_chair else ["Довжина", "Ширина", "Висота"]
    lines = []

    def parts(d):
        return [x.strip() for x in d.replace("×", "*").replace("x", "*").split("*") if x.strip()]

    def dim_lines(d, suffix=""):
        return [(f"{ax}{suffix}", f"{v} см") for ax, v in zip(axes, parts(d))]
    dims = {i["dims_tab"] for i in items if i.get("dims_tab")}
    if len(dims) == 1 and all(i.get("dims_tab") for i in items):
        lines += dim_lines(next(iter(dims)))
    elif dims:
        keys = ["sleep_size", "modules", "seats", "mattress_included", "armrests", "corner_side", "boxes", "mechanism"]
        det = next((k for k in keys if len({i["opts"].get(k, "") for i in items}) > 1 and all(
            len({i.get("dims_tab", "") for i in items if i["opts"].get(k, "") == v} - {""}) <= 1
            for v in {i["opts"].get(k, "") for i in items})), None)
        if not det:
            allp = [parts(d) for d in sorted(dims, key=lambda d: [float(x) for x in parts(d)])]
            for n, ax in enumerate(axes):
                vals = []
                for pp in allp:
                    if n < len(pp) and pp[n] not in vals:
                        vals.append(pp[n])
                if vals:
                    lines.append((ax, " / ".join(vals) + " см"))
        else:
            seen = {}
            for i in items:
                if i.get("dims_tab"):
                    seen.setdefault((i["opts"].get(det, ""), i["dims_tab"]), True)
            for (tag, d), _ in seen.items():
                t = _sleep_text(tag) if det == "sleep_size" and tag else tag
                lines += dim_lines(d, f" ({t})" if t else "")
    def uniq(tag):
        vals = []
        for i in items:
            v = i["opts"].get(tag, "")
            if v and v not in vals:
                vals.append(v)
        return vals
    sl = uniq("sleep_size")
    if sl:
        lines.append(("Спальне місце", "; ".join(_sleep_text(v) for v in sl)))
    mech = uniq("mechanism")
    if mech:
        lines.append(("Механізм", "; ".join(m[0].lower() + m[1:] if m != "Без механізму" else "без механізму" for m in mech)))
    seats = uniq("seats")
    if seats:
        lines.append(("Кількість місць", "; ".join(seats)))
    niche = uniq("storage_niche")
    if niche:
        lines.append(("Ніша для речей", "; ".join(n.lower() for n in niche)))
    mt = uniq("mattress_included")
    if mt:
        lines.append(("Основа / матрац", "; ".join(m[0].lower() + m[1:] for m in mt)))
    m = re.search(r"Навантаження:\s*([^.]+?)\.", p0["description"])
    if m:
        lines.append(("Навантаження", m.group(1).strip()))
    lines.append(("Гарантія", "18 місяців"))
    return _rt(lines)


AQUASTOP_URL = "https://pqqkqm-nz.myshopify.com/products/comefor-namatratsnyk-akvastop"

CARE_SOFT = [
    "Регулярно чистіть пилососом або м'якою щіткою.",
    "Плями прибирайте відразу чистою вологою білою тканиною. Не втирайте пляму.",
    "Для чищення використовуйте м'який мильний розчин. Не застосовуйте розчинники, хлор і абразиви.",
    "Не сушіть феном і не ставте біля батарей та на пряме сонце.",
    "Не сідайте на підлокітники і спинку, дотримуйтесь вказаних навантажень.",
]
CARE_HARD = [
    "Протирайте м'якою злегка вологою тканиною, потім сухою.",
    "Не використовуйте абразивні засоби, розчинники й гарячі предмети без підставки.",
    "Не залишайте на поверхні воду, вона шкодить дереву.",
    "Тримайте меблі подалі від батарей і прямого сонця, вологість у приміщенні 40–60%.",
]


def build_tab_materials(items):
    pt = items[0]["product_type"]
    if pt in ("Матраци", "Безпружинні матраци"):
        li = [
            {"type": "list-item", "children": [
                {"type": "text", "value": "Для продовження строку служби матраца рекомендуємо використовувати водонепроникний наматрацник: "},
                {"type": "link", "url": AQUASTOP_URL,
                 "children": [{"type": "text", "value": "наматрацник Аквастоп"}]},
                {"type": "text", "value": "."}]},
            {"type": "list-item", "children": [{"type": "text", "value": "Плями видаляйте теплою водою або м'яким мильним розчином."}]},
            {"type": "list-item", "children": [{"type": "text", "value": "За потреби зверніться до послуг хімчистки."}]},
        ]
        return json.dumps({"type": "root", "children": [{"type": "list", "listType": "unordered", "children": li}]},
                          ensure_ascii=False, separators=(",", ":"))
    if pt in ("Наматрасники", "Подушки", "Ковдри"):
        return ""  # окремий догляд — текст не додаємо
    soft = any(i["opts"].get("fabric") or i["opts"].get("back_fabric") for i in items)
    tips = CARE_SOFT if soft else CARE_HARD
    li = [{"type": "list-item", "children": [{"type": "text", "value": t}]} for t in tips]
    if soft and pt in ("М'які ліжка", "Кутові ліжка", "Дитячі ліжка") and any(
            i["opts"].get("mattress_included") == "З матрацом" for i in items):
        li.insert(0, {"type": "list-item", "children": [
            {"type": "text", "value": "Для продовження строку служби матраца рекомендуємо використовувати водонепроникний наматрацник: "},
            {"type": "link", "url": AQUASTOP_URL, "children": [{"type": "text", "value": "наматрацник Аквастоп"}]},
            {"type": "text", "value": "."}]})
    return json.dumps({"type": "root", "children": [{"type": "list", "listType": "unordered", "children": li}]},
                      ensure_ascii=False, separators=(",", ":"))


def stock_qty(p):
    """Кількість для Shopify за ознакою наявності (кількості в постачальників ненадійні):
    в наявності — 100, немає — 0 (варіант стає недоступним)."""
    if p["source"] == "akord":  # ВНД / Vinadi самі не знають залишків — завжди в наявності
        return 100
    return 100 if p["available"] else 0


def comefor_available(stock):
    t = (stock or "").strip().lower()
    if not t:
        return False
    if any(w in t for w in ("немає", "нет", "відсутн", "закінч", "закончил", "замовлення", "заказ", "out")):
        return False
    return "наявн" in t or "наличи" in t or t in ("true", "1", "yes")


# ---------- вивід ----------

NO_IMAGE_SOURCES = {"akord", "woodman"}


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
            ("available", "true" if (p["available"] or p["source"] == "akord") else "false"),
            ("quantity", stock_qty(p)),
            ("instock", stock_qty(p)), ("barcode", p["barcode"]),
            ("meta_title", p["meta_title"]), ("meta_description", p["meta_description"]),
            ("meta_keywords", p["meta_keywords"]), ("alias", p["handle"]),
            ("description", p["description"]),
            ("spalne_mistse", p["sleep"]), ("dovzhyna", p["length"]),
            ("shyryna", p["width"]), ("vysota", p["height"]),
            ("tab_characteristics", p.get("tab_characteristics", "")),
            ("tab_materials", p.get("tab_materials", "")),
        ]
        for tag, val in fields:
            ET.SubElement(item, tag).text = "0" if val == 0 else str(val or "")
        for tag in OPT_TAGS:
            ET.SubElement(item, tag).text = str(p["opts"].get(tag, "") or "")
        names, vals = p.get("option_names", []), p.get("option_values", [])
        for n in range(3):
            ET.SubElement(item, f"option{n + 1}_name").text = names[n] if n < len(names) else ""
            ET.SubElement(item, f"option{n + 1}_value").text = vals[n] if n < len(vals) else ""
        # Фото ВНД і Woodman у фід не віддаємо: їх додають і обрізають вручну в Shopify
        imgs = [] if p["source"] in NO_IMAGE_SOURCES else p["images"]
        ET.SubElement(item, "variant_image").text = imgs[0] if imgs else ""
        images_el = ET.SubElement(item, "images")
        for img in imgs:
            ET.SubElement(images_el, "image").text = img
    raw = ET.tostring(catalog, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def parse_manual(_text=None):
    """Ручні товари ВНД, яких немає у вигрузці постачальника (manual_products.json)."""
    out = []
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manual_products.json")
    if not os.path.exists(path):
        return out
    for m in json.load(open(path, encoding="utf-8")):
        out.append(product(
            source="akord", sku=m["sku"], handle=m["handle"], name=m["name"], price=m["price"],
            product_type=m["product_type"], images=m["images"], description=m["description"],
            available=True, vendor="ВНД", instock="100",
            meta_title=m["name"] + " — Акорд Меблі",
        ))
    return out


def main():
    sources = [
        ("Акорд (ВНД)", "AKORD_CSV", parse_akord, True),
        ("Vetro", "VETRO_XML", parse_vetro, True),
        ("Come-For", "COMEFOR_XML", parse_comefor, True),
        ("Woodman", "WOODMAN_CSV", parse_woodman, os.environ.get("WOODMAN_ENABLED", "1") == "1"),
    ]
    all_products, failed = [], []
    all_products += parse_manual()
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
