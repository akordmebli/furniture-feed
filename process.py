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
    "Додатки": "Додатки",
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


def cm3(*vals):
    """Розміри одного товару в см. Якщо хоч один розмір < 100, усі вже в см (415*150*71 — це см, а не мм)."""
    nums = []
    for v in vals:
        try:
            nums.append(float(str(v).replace(",", ".").strip()))
        except (ValueError, TypeError):
            nums.append(0)
    if any(0 < x < 100 for x in nums):
        return [str(round(x)) if x > 0 else "" for x in nums]
    return [cm(v) for v in vals]


def title_overrides(title, leaf):
    t = title.lower()
    if t.startswith("модульний диван"):
        return "Модульні дивани"
    if "буфет" in t or "тв-тумба" in t:
        return "Буфети і ТВ-тумби"
    if "барний стілець" in t or t.startswith("стілець барний"):
        return "Барні стільці"  # садові барні стільці: тег «Садові меблі» додаємо нижче
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
    if t.startswith("крісло") and any(k in t for k in ("henry", "cooper", "vero", "topaz", "teren", "stochol", "stockholm", "borno")):
        return "Обідні стільці"
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
    if "бортик" in base["name"].lower():
        base["product_type"] = "Додатки"  # окрема колекція, не в меню
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

# механізм, якого немає у вигрузці (за назвою товару)
DEFAULT_MECHANISM = {"диван colombo": "Єврокнижка", "диван коломбо": "Єврокнижка", "диван хеппі": "Єврокнижка", "диван even": "Покроковий"}

# Нерозкладні дивани: у вигрузці стоїть «спальне місце», якого немає
NO_SLEEP_ALIASES = {"divan-bloom"}

VALUE_FIXES = {"mechanism": {"Крокуючий": "Покроковий"}}


def norm_size_value(tag, val):
    """Розміри в одному форматі: см (1500*1900 → 150*190), тумба — «80х120»."""
    val = VALUE_FIXES.get(tag, {}).get(val, val)
    # одиниці виміру вказані в назві фільтра — у значеннях опцій «см» не пишемо
    val = re.sub(r"(?<=\d)\s*см\.?$", "", val).strip()
    if tag == "sleep_size":
        m = re.fullmatch(r"(\d+)\s*[*xхX×]\s*(\d+)", val)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if max(a, b) >= 400:
                a, b = round(a / 10), round(b / 10)
            return f"{a}*{b}"
    if tag == "tabletop_size":
        return val.replace("x", "х").replace("X", "х")
    return val


FABRIC_ORDER = {"А": 0, "Б": 1, "В": 2, "Г": 3, "Д": 4, "Е": 5, "Ж": 6, "З": 7}


def natural_key(tag, val):
    if val in ("Стандартна", "Стандартні ніжки"):
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
        if not opts.get("mechanism") and name.strip().lower() in DEFAULT_MECHANISM:
            opts["mechanism"] = DEFAULT_MECHANISM[name.strip().lower()]
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
        # у ліжок спальне місце не довше 200 см (у джерелі бувають помилки на кшталт «140*210» у Марсель ІІ)
        if "ліжк" in leaf.lower() and opts.get("sleep_size"):
            opts["sleep_size"] = re.sub(r"(?<=\*)21\d$", "200", str(opts["sleep_size"]))
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
            **dict(zip(("length", "width", "height"),
                       cm3(opts.get("length_opt", ""), opts.get("width_opt", ""), opts.get("height_opt", "")))),
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
            params={k: v for k, v in params.items() if k and v},
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
            height=height, params=params,
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
            params={k: v.strip() for k, v in uarow.items() if k and v.strip() not in ("", "–", "-")},
            # дерев'яні ліжка Woodman без підйомного механізму й ніші — для фільтрів, як у ВНД/Vinadi
            opts={"mechanism": "Без механізму", "storage_niche": "Немає"} if re.search(r"\bліжко\b", name.lower()) else {},
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


def _wm_num(v):
    m = re.search(r"\d+", str(v or ""))
    return int(m[0]) if m else 0


def split_woodman(p):
    n = p["name"]
    opts = {}
    # ліжка: розмір — це спальне місце; опція зветься як у ВНД/Vinadi («Спальне місце», 140*200),
    # щоб працював спільний фільтр вітрини
    bed = bool(re.search(r"\bліжко\b", n.lower()))  # не «приліжкова»
    if ", " in n:
        n, fabric = n.rsplit(", ", 1)
        fabric = fabric.strip()
        # «…, карамель» / «…, натурального кольору» — це колір каркаса, а не тканини (тумба LOFT з шухлядою)
        key = "Колір каркаса" if FRAME_RE.fullmatch(" " + fabric) else "Колір тканини"
        opts[key] = fabric
    sz = SIZE_RE.search(n)
    if sz:
        if bed:
            opts["Спальне місце"] = f"{sz[1]}*{sz[2]}"
        else:
            opts["Розмір"] = f"{sz[1]}×{sz[2]}"
        n = (n[:sz.start()] + n[sz.end():]).strip()
    elif bed:
        prm = p.get("params", {})
        w = _wm_num(prm.get("ШИРИНА СПАЛЬНОГО МІСЦЯ, см"))
        ln = _wm_num(prm.get("ДОВЖИНА СПАЛЬНОГО МІСЦЯ, см"))
        if w and ln:
            opts["Спальне місце"] = f"{min(w, ln)}*{max(w, ln)}"
    if "Спальне місце" in opts:
        p["sleep"] = opts["Спальне місце"].replace("*", "×")
    fm = FRAME_RE.search(n)
    if fm:
        opts["Колір каркаса"] = fm[1].strip()
        n = n[:fm.start()].strip()
    return n, opts


SPLITTERS = {"comefor": split_comefor, "vetro": split_vetro, "woodman": split_woodman}
OPTION_ORDER = ["Спальне місце", "Розмір", "Колір каркаса", "Колір тканини", "Колір"]
KEEP_SINGLE_OPTS = {"Спальне місце"}  # лишаємо опцією навіть з одним значенням — для фільтра



AKORD_OPT_LABELS = {
    "sleep_size": "Спальне місце", "fabric": "Категорія тканини", "tabletop_size": "Розмір стільниці",
    "mattress_included": "Матрац", "back_fabric": "Тканина спинки", "modules": "Модулі",
    "dimensions": "Розміри", "leg_color": "Колір ніжок", "frame_color": "Колір каркаса",
    "mechanism": "Механізм", "pillows": "Подушки", "material": "Матеріал",
    "length_opt": "Довжина", "width_opt": "Ширина", "height_opt": "Висота",
    "corner_side": "Сторона кута", "tabletop_color": "Колір стільниці", "armrests": "Підлокітники", "seats": "Кількість місць",
    "boxes": "Короби", "storage_niche": "Ніша для речей", "legs": "Ніжки",
}
# Характеристики, що впливають на ціну (за порядком пріоритету). Решта — лише метафілди,
# і в опції потрапляють тільки якщо інакше варіанти збігаються (щоб не було дублікатів).
AKORD_PRICE_OPTS = ["sleep_size", "fabric", "tabletop_size", "mattress_included", "boxes", "back_fabric", "modules", "legs"]


def _akord_apply(items, tags):
    head, tail = tags[:2], tags[2:]
    cols = [[t] for t in head] + ([tail] if tail else [])
    # «Ніжки» разом з іншою опцією в одній колонці: «З матрацом» / «З матрацом + підвищені ніжки»
    def gname(g):
        rest = [t for t in g if t != "legs"]
        return " і ".join(AKORD_OPT_LABELS[t] for t in (rest or g))

    def gval(i, g):
        rest = [t for t in g if t != "legs"]
        legs = i["opts"].get("legs", "") if "legs" in g else ""
        if not rest:
            return legs or "—"
        v = " / ".join(i["opts"].get(t, "") for t in rest if i["opts"].get(t, "")) or "—"
        return f"{v} + підвищені ніжки" if legs == LEGS_HIGH else v
    names = [gname(g) for g in cols]
    # кома в значенні опції розбиває його на два варіанти під час імпорту -> «1,5» стає «1.5»
    vals = [[gval(i, g).replace(",", ".") for g in cols] for i in items]
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


# М'які ліжка ВНД/Vinadi: опція «Ніжки» (стандартні / підвищені, підвищені — дорожче)
LEGS_EXCLUDE = {"machiato", "lessa", "strong", "arno", "infinity", "mojo", "everlay",
                "blade", "blade ii", "lavo", "mellow", "senna"}
LEGS_1200 = ("esme", "olivia", "riff", "stone", "monroe", "freya", "астон", "aston light",
             "marsello", "марсель")
LEGS_STD, LEGS_HIGH = "Стандартні ніжки", "Підвищені ніжки"


def _legs_model(p):
    n = " ".join(p["name"].lower().replace("’", "'").split())
    if p["product_type"] == "М'які ліжка" and n.startswith("м'яке ліжко "):
        return n[len("м'яке ліжко "):].strip()
    if n == "дитяче м'яке ліжко riff":
        return "riff"
    return None


def add_legs_variants(products):
    out = []
    for p in products:
        out.append(p)
        if p.get("source") != "akord":
            continue
        model = _legs_model(p)
        if not model or model in LEGS_EXCLUDE:
            continue
        add = 1200 if any(model.startswith(k) for k in LEGS_1200) else 950
        p["opts"] = {**p["opts"], "legs": LEGS_STD}
        hi = {**p, "opts": {**p["opts"], "legs": LEGS_HIGH}, "tags": list(p["tags"]),
              "sku": f'{p["sku"]}-HL' if p["sku"] else "", "barcode": "",
              "price": f'{float(p["price"]) + add:.2f}'}
        out.append(hi)
    return out


def group_variants(products):
    """Об'єднує постачальницькі позиції в один товар з варіантами.
    Фід лишається плоским (один <item> = один варіант), спільний handle групує варіанти."""
    products = add_legs_variants(products)
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
        if len(items) > 1 and not all("Розмір" in i["group_opts"] or "Спальне місце" in i["group_opts"]
                                      for i in items):
            dims = {(i["length"], i["width"]) for i in items}
            if len(dims) > 1 and all(i["length"] and i["width"] for i in items):
                for i in items:
                    i["group_opts"] = {"Розмір": f'{i["width"]}×{i["length"]}', **i["group_opts"]}
        names = [n for n in OPTION_ORDER if any(n in i["group_opts"] for i in items)]
        names = [n for n in names if len({i["group_opts"].get(n, "—") for i in items}) > 1
                 or (n in KEEP_SINGLE_OPTS and all(n in i["group_opts"] for i in items))][:3]
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
            i["tab_3d"] = build_tab_3d(i["handle"])
            i["tab_details"] = build_tab_details(i["handle"])
    # інші постачальники (Vetro, Woodman, Come-For): вкладки картки теж, як у ВНД/Vinadi
    other = {}
    for p in out:
        if p["source"] != "akord":
            other.setdefault(p["handle"], []).append(p)
    for items in other.values():
        tab = build_tab_characteristics_other(items)
        mat = build_tab_materials(items)
        for i in items:
            i["tab_characteristics"] = tab
            i["tab_materials"] = mat
            i["tab_3d"] = build_tab_3d(i["handle"])
            i["tab_details"] = build_tab_details(i["handle"]) or (
                build_tab_details_comefor(items) if i["source"] == "comefor" else
                build_tab_details_woodman(items) if i["source"] == "woodman" else
                build_tab_details_vetro(items) if i["source"] == "vetro" else "")
    # варіанти від меншого до більшого: розмір, категорія тканини (А→Ж) та інші цінові опції
    order = {h: n for n, h in enumerate(akord)}
    sort_tags = AKORD_PRICE_OPTS + [t for t in AKORD_OPT_LABELS if t not in AKORD_PRICE_OPTS]
    key = lambda p: (order[p["handle"]], [natural_key(t, p["opts"].get(t, "")) for t in sort_tags])
    others = [p for p in out if p["source"] != "akord"]
    oorder = {}
    for p in others:
        oorder.setdefault(p["handle"], len(oorder))
    first = {}
    for p in others:
        for i, v in enumerate(p.get("option_values") or []):
            first.setdefault((p["handle"], i, v), len(first))

    def okey(p):  # розміри — від меншого до більшого, текстові значення — у вихідному порядку
        ks = []
        for i, v in enumerate(p.get("option_values") or []):
            nums = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", v or "")]
            ks.append((0, tuple(nums), 0) if nums else (1, (), first[(p["handle"], i, v)]))
        return (oorder[p["handle"]], ks)
    out = sorted(others, key=okey) + sorted((p for p in out if p["source"] == "akord"), key=key)
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


CHAIR_TYPES = ("Обідні стільці", "Барні стільці", "М'які крісла")
SOFT_TYPES = ("М'які крісла", "Прямі дивани", "Кутові дивани", "Модульні дивани", "Пуфи", "М'які ліжка", "Кутові ліжка")
SOFT_WORDS = ("велюр", "рогожк", "тканин", "букле", "шеніл", "флок", "мікрофібр")


COMEFOR_CHAR = [  # (параметр у фіді, підпис, чи приводити до нижнього регістру)
    ("Тип", "Тип", True), ("Жорсткість", "Жорсткість", True), ("Зональність", "Зони жорсткості", False),
    ("Навантаження на 1 сп. місце", "Навантаження на спальне місце", True),
    ("Двосторонній", "Двосторонній", True), ("Знімний чохол", "Знімний чохол", True),
    ("Єврокаркас", "Єврокаркас", True), ("Водонепроникний", "Водонепроникний", True),
    ("Придатне для прання", "Придатне для прання", True), ("Антикіготь", "Антикіготь", True),
]
COMEFOR_DETAILS = [("Матеріали", "Матеріали"), ("Тканина чохла", "Тканина чохла"), ("Основний блок", "Основний блок")]


def _cf_vals(items, key, lower=False):
    out = []
    for i in items:
        v = " ".join(str((i.get("params") or {}).get(key, "")).split())
        if lower:
            v = v.lower()
        if v and v not in out:
            out.append(v)
    return out


def _cf_warranty(v):
    return re.sub(r"(\d+,5)\s+року\b", r"\1 роки", v)  # «два з половиною роки»


def _cf_num_sort(vals):
    def k(x):
        m = re.search(r"\d+(?:[.,]\d+)?", x)
        return float(m.group(0).replace(",", ".")) if m else 0
    return sorted(vals, key=k)


def build_tab_characteristics_comefor(items):
    lines = []
    sizes = []
    for i in items:
        if i.get("sleep") and i["sleep"] not in sizes:
            sizes.append(i["sleep"])
    if sizes:
        lines.append(("Розміри", "; ".join(_cf_num_sort(sizes)) + " см"))
    hs = _cf_num_sort(_cf_vals(items, "Висота"))
    if hs:
        h = [x.replace(".", ",") for x in hs]
        lines.append(("Висота", (h[0] if len(h) == 1 else f"{h[0]}–{h[-1]}") + " см"))
    for key, label, low in COMEFOR_CHAR:
        v = _cf_vals(items, key, low)
        if v:
            lines.append((label, "; ".join(v)))
    w = [_cf_warranty(x) for x in _cf_vals(items, "Гарантія")]
    w = list(dict.fromkeys(w))
    if w:
        lines.append(("Гарантія", "; ".join(_cf_num_sort(w))))
    return _rt(lines)


def build_tab_details_comefor(items):
    lines = []
    for key, label in COMEFOR_DETAILS:
        v = _cf_vals(items, key)
        if v:
            lines.append((label, "; ".join(v)))
    wt = _cf_vals(items, "Вага за 1 м² / кг")
    if wt:
        lines.append(("Вага 1 м²", "; ".join(x + " кг" for x in _cf_num_sort(wt))))
    return _rt(lines)


# Woodman: (колонка аркуша, підпис, суфікс)
WOODMAN_CHAR = [
    ("РОЗМІР У СКЛАДЕНОМУ ПОЛОЖЕННІ, см", "Розмір у складеному положенні", " см"),
    ("РОЗМІР У РОЗКЛАДЕНОМУ ПОЛОЖЕННІ, см", "Розмір у розкладеному положенні", " см"),
    ("РОЗМІР СИДІННЯ, см", "Розмір сидіння", " см"),
    ("ВИСОТА СИДІННЯ, см", "Висота сидіння", " см"),
    ("ГЛИБИНА СИДІННЯ, см", "Глибина сидіння", " см"),
    ("ВИСОТА СПИНКИ, см", "Висота спинки", " см"),
    ("ВИСОТА ПІДЛОКІТНИКА, см", "Висота підлокітника", " см"),
    ("ВИСОТА УЗГОЛІВ’Я, см", "Висота узголів’я", " см"),
    ("ДОВЖИНА СПАЛЬНОГО МІСЦЯ, см", "Довжина спального місця", " см"),
    ("ШИРИНА СПАЛЬНОГО МІСЦЯ, см", "Ширина спального місця", " см"),
    ("ВИСОТА НІЖОК, см", "Висота ніжок", " см"),
    ("ОСНОВА ПІД МАТРАЦ", "Основа під матрац", ""),
    ("МАТРАЦ У КОМПЛЕКТІ", "Матрац у комплекті", ""),
    ("РОЗМІР МАТРАЦА, см", "Розмір матраца", " см"),
    ("ТОВЩИНА МАТРАЦА, см", "Товщина матраца", " см"),
    ("ШУХЛЯДА У КОМПЛЕКТІ", "Шухляда у комплекті", ""),
    ("ДОПУСТИМА ВАГА НАВАНТАЖЕННЯ, кг", "Допустиме навантаження", " кг"),
    ("ЗАГАЛЬНА ВАГА ВИРОБУ, кг", "Вага виробу", " кг"),
    ("ГАРАНТІЯ НА ВИРІБ", "Гарантія", ""),
]
WOODMAN_DETAILS = [
    ("КАРКАС ВИРОБУ", "Каркас"),
    ("МАТЕРІАЛ СИДІННЯ / МАТРАЦА / ПОДУШОК", "Сидіння / матрац / подушки"),
    ("МАТЕРІАЛ НІЖОК", "Ніжки"),
    ("МАТЕРІАЛ УЗГОЛІВ’Я", "Узголів’я"),
    ("МАТЕРІАЛ СКЛА", "Скло"),
    ("КОМПЛЕКТАЦІЯ", "Комплектація"),
    ("КРАЇНА ПОХОДЖЕННЯ", "Країна походження"),
]


# Vetro: (параметр фіду, підпис, суфікс)
VETRO_CHAR = [
    ("Максимальна довжина стільниці, см", "Довжина у розкладеному вигляді", " см"),
    ("Діаметр, см", "Діаметр", " см"),
    ("Ширина сидіння, см", "Ширина сидіння", " см"),
    ("Глибина сидіння, см", "Глибина сидіння", " см"),
    ("Максимальна глибина сидіння, см", "Максимальна глибина сидіння", " см"),
    ("Висота до сидіння, см", "Висота до сидіння", " см"),
    ("Висота до підлокітників, см", "Висота до підлокітників", " см"),
    ("Висота посадки дивана, см", "Висота посадки", " см"),
    ("Глибина посадки дивана, см", "Глибина посадки", " см"),
    ("Форма", "Форма", ""),
    ("Вид", "Вид", ""),
    ("Механізм розкладки", "Механізм розкладки", ""),
    ("Характеристики", "Особливості", ""),
    ("Складання", "Складання", ""),
    ("Вага, кг", "Вага", " кг"),
]
VETRO_DETAILS = [
    ("Матеріал основи", "Основа"),
    ("Матеріал каркасу", "Каркас"),
    ("Матеріал ніжок", "Ніжки"),
    ("Матеріал стільниці", "Стільниця"),
    ("Матеріал вкладки", "Вкладка"),
    ("Матеріал оббивки", "Оббивка"),
    ("Наповнювач сидіння", "Наповнювач сидіння"),
    ("Наповнювач спинки", "Наповнювач спинки"),
]


def _wm_vals(items, key, suffix=""):
    out = []
    for i in items:
        v = " ".join(str((i.get("params") or {}).get(key, "")).split()).replace(" х ", "×").replace(" x ", "×")
        if v and v not in out:
            out.append(v)
    return "; ".join(x + suffix for x in out) if out else ""


def build_tab_details_woodman(items):
    return _rt([(label, _wm_vals(items, key)) for key, label in WOODMAN_DETAILS])


def build_tab_details_vetro(items):
    rows = []
    for key, label in VETRO_DETAILS:
        v = _wm_vals(items, key)
        if v:
            rows.append((label, v[:1].upper() + v[1:] if label in ("Основа", "Каркас", "Ніжки", "Стільниця", "Вкладка", "Оббивка") else v))
    return _rt(rows)


def build_tab_characteristics_other(items):
    """Вкладка «Характеристики» для Vetro / Woodman / Come-For: габарити, кольори."""
    p0 = items[0]
    if p0["source"] == "comefor":
        return build_tab_characteristics_comefor(items)
    is_chair = p0["product_type"] in CHAIR_TYPES

    def vals(key):
        out = []
        for i in items:
            v = str(i.get(key, "") or "").strip()
            if v and v not in out:
                out.append(v)
        return sorted(out, key=lambda x: float(x) if x.replace(".", "", 1).isdigit() else 0)

    ln, wd, ht = vals("length"), vals("width"), vals("height")
    lines = []
    if is_chair and not ln:
        lines.append(("Ширина", " / ".join(wd) + " см" if wd else ""))
    elif is_chair:
        lines += [("Ширина", " / ".join(ln) + " см"), ("Глибина", " / ".join(wd) + " см" if wd else "")]
    else:
        lines += [("Довжина", " / ".join(ln) + " см" if ln else ""), ("Ширина", " / ".join(wd) + " см" if wd else "")]
    lines.append(("Висота", " / ".join(ht) + " см" if ht else ""))
    for label in ("Колір каркаса", "Колір тканини", "Колір"):
        seen = []
        for i in items:
            for n, v in zip(i.get("option_names") or [], i.get("option_values") or []):
                if n == label and v and v != "—" and v not in seen:
                    seen.append(v)
        if seen:
            lines.append((label, "; ".join(seen)))
    if p0["source"] == "woodman":
        for key, label, suf in WOODMAN_CHAR:
            lines.append((label, _wm_vals(items, key, suf)))
    if p0["source"] == "vetro":
        for key, label, suf in VETRO_CHAR:
            v = _wm_vals(items, key, suf)
            if label == "Складання":
                v = v.replace("потребує складання", "потрібне").replace("не потрібне", "не потрібне")
            lines.append((label, v.replace(".", ",") if suf else v))
    # гарантію додаємо лише там, де вона є у фіді постачальника (Come-For, Woodman)
    return _rt([(k, v) for k, v in lines if v])


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
    if not soft and items[0]["source"] != "akord":
        txt = " ".join(" ".join(i.get("option_values") or []) + " " + i["name"] for i in items).lower()
        soft = pt in SOFT_TYPES or any(w in txt for w in SOFT_WORDS) or any(
            n == "Колір тканини" for i in items for n in (i.get("option_names") or []))
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


def _models_3d():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models_3d.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


MODELS_3D = _models_3d()


def build_tab_3d(handle):
    fid = MODELS_3D.get(handle)
    if not fid:
        return ""
    url = f"https://drive.google.com/drive/folders/{fid}?usp=sharing"
    li = [{"type": "list-item", "children": [
        {"type": "text", "value": "3D-модель: ", "bold": True},
        {"type": "link", "url": url, "children": [{"type": "text", "value": "переглянути і завантажити"}]}]}]
    return json.dumps({"type": "root", "children": [{"type": "list", "listType": "unordered", "children": li}]},
                      ensure_ascii=False, separators=(",", ":"))


def _load_json(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


TAB_DETAILS = _load_json("tab_details.json")


def build_tab_details(handle):
    lines = TAB_DETAILS.get(handle)
    if not lines:
        return ""
    return _rt([(k, v) for k, v in lines])


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


# ---------- форма стільниці (метаполе custom.tabletop_shape, фільтр «Форма стільниці») ----------
# моделі ВНД/Vinadi/Woodman — форма за фото (у джерелах її немає); квадратні рахуємо як прямокутні
SHAPE_BY_MODEL = {
    "RONDO": ["Кругла"], "TORONTO": ["Кругла"], "PINK": ["Кругла"], "ELVERA": ["Кругла"], "IRIS": ["Кругла"],
    "AREN": ["Кругла"], "NORD": ["Кругла"], "FIJI": ["Кругла"], "STELIO": ["Кругла"], "СОФІ": ["Кругла"],
    "ALLEGRO": ["Кругла"],
    "LIGHT": ["Прямокутна"], "KASTELLO": ["Прямокутна"], "HEVI": ["Прямокутна"], "BEVERLEY": ["Прямокутна"],
    "GOA": ["Прямокутна"], "MILOS": ["Прямокутна"], "EDMOND": ["Прямокутна"], "CHARLOTTE": ["Прямокутна"],
    "STYLE": ["Прямокутна"], "ДЕФТ": ["Прямокутна"], "MEXICO": ["Прямокутна"], "КОРТІНА": ["Прямокутна"],
    "HAROLD": ["Кругла", "Прямокутна"], "BELFORT": ["Овальна"],
}
SHAPE_WORDS = [("прямокут", "Прямокутна"), ("квадрат", "Прямокутна"), ("овал", "Овальна"), ("кругл", "Кругла"),
               ("трикут", "Трикутна")]


def tabletop_shape(p):
    """Форма стільниці для столів: модель → «Форма: …» у даних постачальника → діаметр/Ø → розмір «ДхШ»."""
    if not re.search(r"стіл(?!ець|ьц)|стол|консол", p["name"].lower()):
        return []
    up = p["name"].upper()
    for k, v in SHAPE_BY_MODEL.items():
        if re.search(rf"(?<![A-ZА-ЯІЇЄҐ]){k}(?![A-ZА-ЯІЇЄҐ])", up):
            return v
    if p["product_type"] not in ("Обідні столи", "Журнальні столики і консолі", "Садові меблі"):
        return []
    blob = json.dumps(p, ensure_ascii=False, default=str).lower()
    m = re.search(r"форма[^а-яіїєґ]{0,60}(прямокут|квадрат|овал|кругл|трикут)", blob)
    if m:
        return [v for w, v in SHAPE_WORDS if m.group(1) == w]
    if "кругл" in p["name"].lower() or "ø" in blob or "⌀" in blob or re.search(r"діаметр[^0-9]{0,40}\d", blob):
        return ["Кругла"]
    if re.search(r"\d\s*[xх×*]\s*\d", str(p.get("opts", {}).get("tabletop_size", ""))):
        return ["Прямокутна"]
    return []


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
            ("tab_3d", p.get("tab_3d", "")),
            ("tab_details", p.get("tab_details", "")),
            ("tabletop_shape", ", ".join(tabletop_shape(p))),
        ]
        for tag, val in fields:
            ET.SubElement(item, tag).text = "0" if val == 0 else str(val or "")
        for tag in OPT_TAGS:
            val = "" if p.get("no_dims") and tag in ("dimensions", "sleep_size") else p["opts"].get(tag, "")
            ET.SubElement(item, tag).text = str(val or "")
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


def apply_brands(items):
    """Виробник: Vinadi (пріоритет, vinadi_aliases.json) або ВНД. Магазин — лише продавець:
    «від АКОРД МЕБЛІ» (як виробник) → «від <бренд>». «Доставка ... від АКОРД МЕБЛІ» лишається."""
    try:
        vin = set(json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vinadi_aliases.json"), encoding="utf-8")))
    except OSError:
        vin = set()
    def fix(text, brand):
        if not text:
            return text
        def rep(m):
            pre = text[max(0, m.start() - 40):m.start()].lower()
            if "доставк" in pre:
                return m.group(0)
            return m.group(1) + brand
        text = re.sub(r"(?i)(від\s+)акорд\s+меблі", rep, text)
        text = re.sub(r"\.\s+АКОРД МЕБЛІ\.", ". Виробник — %s." % brand, text)
        return text
    # модульні, що показуємо і в «Кутових диванах» (тег → колекція за правилом TAG)
    corner_too = {"modulniy-divan-mondi", "modulniy-divan-morani", "modulniy-divan-casio",
                  "modulniy-divan-siena", "modulniy-divan-ruby", "modulniy-divan-lemmo", "modulniy-divan-lario"}
    for p in items:
        if p.get("source") == "akord" and p.get("handle") in corner_too and "Кутові дивани" not in p["tags"]:
            p["tags"].append("Кутові дивани")
    # усі товари серій Allegro, Mexico, Layti, крім тумбочок і ліжок, показуємо і в «Садових меблях» (тег → колекція за правилом TAG)
    for p in items:
        if p["product_type"] == "Барні стільці" and "садов" in p["name"].lower() and "Садові меблі" not in p["tags"]:
            p["tags"].append("Садові меблі")
    for p in items:
        if any(k in p["name"].lower() for k in ("allegro", "mexico", "layti")) and p["product_type"] not in ("Тумбочки", "Каркаси ліжок") and "Садові меблі" not in p["tags"]:
            p["tags"].append("Садові меблі")
    # односпальні ліжка та диван Тімон показуємо і в «Дитячих ліжках» (тег → колекція за правилом TAG)
    for p in items:
        n = p["name"].lower()
        if ((n.startswith("односпальне ліжко") and p["product_type"] == "Каркаси ліжок") or n == "диван тімон") and "Дитячі ліжка" not in p["tags"]:
            p["tags"].append("Дитячі ліжка")
    # ці крісла показуємо і в «Обідніх кріслах», і в «Обідніх стільцях» (теги → колекції за правилом TAG)
    dining_armchairs = {"крісло pink", "крісло noble", "крісло честер", "крісло spiner",
                        "крісло apex", "крісло selen", "крісло далас"}
    for p in items:
        if p["name"].lower().strip() in dining_armchairs:
            for t in ("Обідні крісла", "Обідні стільці"):
                if t not in p["tags"]:
                    p["tags"].append(t)
    # стільці з підлокітниками, «Крісла» серед обідніх стільців і Асті — також в «Обідніх кріслах» (тег → колекція)
    for p in items:
        if p["product_type"] != "Обідні стільці" or "Обідні крісла" in p["tags"]:
            continue
        n = p["name"].lower().strip()
        blob = json.dumps(p, ensure_ascii=False, default=str).lower().replace("не сідайте на підлокітники", "")
        if n.startswith("крісло") or n == "стілець асті" or ("підлокітн" in blob and "без підлокітн" not in blob):
            p["tags"].append("Обідні крісла")
    # столи з круглою стільницею (є діаметр або Ø у розмірі стільниці) — у «Круглих столах» (тег → колекція)
    for p in items:
        if not re.search(r"стіл(?!ець|ьц)|стол", (p["product_type"] + " " + p["name"]).lower()) or "Круглі столи" in p["tags"]:
            continue
        blob = json.dumps(p, ensure_ascii=False, default=str).lower()
        if "ø" in blob or "⌀" in blob or re.search(r"діаметр[^0-9]{0,40}\d", blob) \
                or re.search(r"форма[^,}]{0,12}кругл", blob):
            p["tags"].append("Круглі столи")
    # дивани без механізму і без спального місця (модулі з «розкладне» не чіпаємо) — нерозкладні
    for p in items:
        if p["product_type"] in ("Прямі дивани", "Кутові дивани", "Модульні дивани") and "нерозкладний" not in p["tags"] \
                and p.get("opts", {}).get("mechanism", "") in ("", "Без механізму") and not p.get("opts", {}).get("sleep_size") \
                and "lemmo" not in p["name"].lower() \
                and "розкладн" not in str(p.get("opts", {}).get("modules", "")).lower() \
                and not any(k in p["name"].lower() for k in ("allegro", "mexico", "layti")):
            p["tags"].append("нерозкладний")
    for p in items:
        if p.get("source") != "akord" or p.get("vendor") != "ВНД":
            continue
        if p.get("handle") in vin:
            p["vendor"] = "Vinadi"
        brand = p["vendor"]
        p["description"] = fix(p.get("description", ""), brand)
        p["meta_description"] = fix(p.get("meta_description", ""), brand)


# ---------- короткі описи ВНД/Vinadi та meta для всіх ----------
DESC_MAX = 350


def _joinand(xs):
    xs = [x for x in xs if x]
    if not xs:
        return ""
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " і " + xs[-1]


def _short_desc(name, brand, ptype, items):
    """Лаконічний опис за шаблоном: що це, ключові можливості, розміри, оббивка, гарантія, доставка."""
    def uniq(k):
        return list(dict.fromkeys(i.get("opts", {}).get(k, "") for i in items if i.get("opts", {}).get(k, "")))
    mech = [m for m in uniq("mechanism") if m != "Без механізму"]
    sleep = sorted(uniq("sleep_size"), key=lambda v: [float(x) for x in re.findall(r"\d+", v)])
    mattress = set(uniq("mattress_included"))
    niche = "Є" in uniq("storage_niche")
    dims = uniq("dimensions")
    t = (ptype or "").lower()
    parts = []
    if "ліжк" in t:
        if "кутов" in t:
            feat = "зручне кутове ліжко з м'якими бортиками"
        elif "дит" in t:
            feat = "затишне дитяче ліжко з м'яким узголів'ям"
        else:
            feat = "затишне ліжко з м'яким узголів'ям"
        extra = []
        if any("Газов" in m for m in mech):
            extra.append("газовим підйомним механізмом")
        if niche:
            extra.append("місткою нішею для білизни")
        parts.append(f"{name} від {brand} — {feat}" + (f", {_joinand(extra)}" if extra else "") + ".")
        s = []
        if {"З матрацом", "Ламельна сітка"} <= mattress:
            s.append("Доступне з матрацом або з ламельною сіткою")
        elif "З матрацом" in mattress:
            s.append("Постачається з матрацом")
        if sleep:
            s.append(("у розмірах спального місця " if len(sleep) > 1 else "спальне місце ") + _joinand(sleep))
        if s:
            txt = ", ".join(s)
            parts.append(txt[0].upper() + txt[1:] + ".")
    elif "диван" in t:
        kind = {"прямі дивани": "прямий диван", "кутові дивани": "кутовий диван",
                "модульні дивани": "модульний диван"}.get(t, "диван")
        if mech:
            lead = f"{name} від {brand} — {kind} з механізмом «{mech[0]}»" if len(mech) == 1 else \
                f"{name} від {brand} — {kind} з механізмами " + _joinand([f"«{m}»" for m in mech])
        else:
            lead = f"{name} від {brand} — {kind} без механізму розкладання"
        parts.append(lead + ".")
        if sleep:
            parts.append("Спальне місце " + _joinand(sleep) + ".")
    else:
        kind = {"м'які крісла": "м'яке крісло", "обідні стільці": "обідній стілець", "пуфи": "м'який пуф",
                "тумбочки": "м'яка тумбочка", "лавки": "м'яка лавка",
                "журнальні столики і консолі": "журнальний столик"}.get(t, "")
        parts.append(f"{name} від {brand}" + (f" — {kind} для дому чи закладу." if kind else "."))
    if len(dims) == 1 and "ліжк" not in t:
        parts.append(f"Розміри: {dims[0].replace('*', '×')} см.")
    if uniq("fabric"):
        parts.append("Обирайте оббивку під свій інтер'єр.")
    lead = " ".join(parts)
    return lead + " Гарантія 18 місяців. Доставка по Україні, оплата частинами.", \
        lead + " Доставка по Україні, оплата частинами."


def apply_short_texts(items):
    groups = {}
    for p in items:
        groups.setdefault(p["handle"], []).append(p)
    for h, g in groups.items():
        p0 = g[0]
        name = p0["name"]
        brand = p0.get("vendor") or ""
        if p0.get("source") == "akord" and len(p0.get("description") or "") > DESC_MAX:
            desc, meta = _short_desc(name, brand, p0.get("product_type", ""), g)
            for p in g:
                p["description"] = desc
                p["meta_description"] = meta
        for p in g:
            if not (p.get("meta_title") or "").strip():
                p["meta_title"] = f"{name} | купити в АКОРД МЕБЛІ"
            if not (p.get("meta_description") or "").strip():
                txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", p0.get("description") or "")).strip()
                lead = f"{name}" + (f" від {brand}" if brand and brand not in name else "") + " — купуйте в АКОРД МЕБЛІ."
                if txt:
                    first = re.split(r"(?<=[.!?])\s", txt)[0]
                    if 20 < len(first) < 160 and name.lower() not in first.lower()[:len(name)+5]:
                        lead += " " + first
                p["meta_description"] = (lead + " Доставка по Україні, оплата частинами.")[:300]
        for p in g:
            p["meta_description"] = fit_meta(p.get("meta_description") or "")


META_MAX = 160


def fit_meta(text, limit=META_MAX):
    """Meta description ≤160 символів: спершу прибираємо другорядні речення, потім обрізаємо по слову."""
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) <= limit:
        return t
    steps = [
        lambda s: s.replace(" Обирайте оббивку під свій інтер'єр.", ""),
        lambda s: s.replace(" Гарантія 18 місяців.", ""),
        lambda s: s.replace("Доставка по Україні, оплата частинами.", "Доставка по Україні."),
        lambda s: re.sub(r" Розміри: [^.]*? см\.", "", s) if re.search(r"Спальне місце", s) else s,
        lambda s: re.sub(r",? у розмірах спального місця [^.]*\.", ".", s),
        lambda s: s.replace(" Доставка по Україні.", ""),
    ]
    for f in steps:
        t = f(t)
        if len(t) <= limit:
            return t
    m = re.match(r"(.+? — купуйте в АКОРД МЕБЛІ\.)", t)
    if m:
        out = m.group(1) + " Доставка по Україні, оплата частинами."
        if len(out) <= limit:
            return out
    sents = re.split(r"(?<=[.!?»])\s+", t)
    out = sents[0]
    rest = sents[1:]
    while rest and len(out) + 1 + len(rest[0]) <= limit:
        out += " " + rest.pop(0)
    if rest and len(out) < 110:
        out += " " + rest[0]
    if len(out) > limit:
        cut = out[:limit - 1]
        if cut.rfind(", ") > limit * 0.6:
            out = cut[:cut.rfind(", ")].rstrip() + "."
        else:
            out = cut.rsplit(" ", 1)[0].rstrip(",;:—– ") + "…"
    return out


def clear_module_dims(items):
    """Модульні товари з «сетом» / «Стандартною»: габарити й спальне місце лишаємо тільки базовій комплектації.
    Окремим модулям у джерелі проставлені ті самі розміри сету — прибираємо їх, щоб не вводити в оману."""
    groups = {}
    for p in items:
        if p.get("opts", {}).get("modules"):
            groups.setdefault(p["name"], []).append(p)
    for name, its in groups.items():
        # «сет» (MORANI, MONDI) або «Стандартна» (SMART) — базова комплектація, у якої розміри правильні
        sets = [p for p in its if any(k in str(p["opts"]["modules"]).lower() for k in ("сет", "стандартн"))]
        if not sets:
            continue
        sd = (sets[0]["length"], sets[0]["width"], sets[0]["height"])
        for p in its:
            if p in sets or (p["length"], p["width"], p["height"]) != sd:
                continue
            p["length"] = p["width"] = p["height"] = ""
            p["sleep"] = ""
            p["no_dims"] = True  # опції не чіпаємо, лише не віддаємо розміри у фід


SOFA_BED_TYPES = ("Прямі дивани", "Кутові дивани", "Модульні дивани", "Нерозкладні дивани", "Дивани для кухні",
                  "М'які ліжка", "Кутові ліжка", "Дитячі ліжка", "Каркаси ліжок")
TABLE_TYPES = ("Обідні столи", "Журнальні столики і консолі", "Круглі столи")


def _size_pair(text):
    m = re.search(r"(\d{2,3})\s*[xхX×*]\s*(\d{2,3})", str(text or ""))
    return (int(m[1]), int(m[2])) if m else None


def unify_filters(products):
    """Єдині фільтри для всіх постачальників (не лише ВНД/Vinadi): механізм у диванів і ліжок,
    спальне місце у футонів, габарити стільців (Довжина = ширина) і столів (зі стільниці)."""
    for p in products:
        if p["source"] == "akord":
            continue  # ВНД/Vinadi заповнюються з таблиці
        pt, name = p.get("product_type", ""), p.get("name", "").lower()
        opts = p.setdefault("opts", {})
        prm = p.get("params", {}) or {}
        futon = "футон" in name
        sofa_like = pt in SOFA_BED_TYPES or (pt == "Садові меблі" and re.search(r"диван|кушетк|футон", name))
        # спальне місце: футони Woodman розкладаються на розмір матраца
        if futon and not p.get("sleep"):
            sz = _size_pair(prm.get("РОЗМІР МАТРАЦА, см"))
            if sz:
                p["sleep"] = f"{min(sz)}×{max(sz)}"
        # механізм: у всіх диванів і ліжок, щоб працював фільтр «Механізм»
        if (sofa_like or futon) and not opts.get("mechanism"):
            vm = (prm.get("Механізм розкладки") or "").strip()
            opts["mechanism"] = "Футон" if futon else (vm[:1].upper() + vm[1:] if vm else "Без механізму")
        # стільці й крісла: як у Vinadi — Довжина = ширина виробу, Ширина = глибина (якщо відома)
        if pt in CHAIR_TYPES and not p.get("length") and p.get("width"):
            p["length"], p["width"] = p["width"], ""
    # столи всіх постачальників: габарити зі стільниці, якщо їх немає
    for p in products:
        if p.get("product_type") in TABLE_TYPES and not (p.get("length") and p.get("width")):
            tt = str(p.get("opts", {}).get("tabletop_size", "") or "")
            sz = _size_pair(tt)
            d = re.search(r"(?:D|Ø|⌀|діаметр)\s*(\d{2,3})", tt, re.I)
            if sz:
                p["length"], p["width"] = str(max(sz)), str(min(sz))
            elif d:
                p["length"] = p["width"] = d[1]


RU_FIXES = [("Премиум", "Преміум"), ("премиум", "преміум"), ("Кидди", "Кідді"), ("забезпечуэ", "забезпечує")]


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

    apply_brands(all_products)
    clear_module_dims(all_products)
    all_products = group_variants(all_products)
    unify_filters(all_products)
    apply_short_texts(all_products)
    os.makedirs("output", exist_ok=True)
    with open("output/feed.xml", "w", encoding="utf-8") as f:
        xml = build_xml(all_products)
        # орфографія: матрац, наматрацник, підматрацник (не «матрас»)
        xml = xml.replace("атрасник", "атрацник").replace("Атрасник", "Атрацник")
        # русизми з фідів постачальників (handle латиницею — не зачіпається)
        for ru, ua in RU_FIXES:
            xml = xml.replace(ru, ua)
        f.write(xml)
    print(f"\nГотово: {len(all_products)} позицій → output/feed.xml")


if __name__ == "__main__":
    main()
