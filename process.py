import os
import csv
import json
import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom
from io import StringIO

with open("mapping.json", encoding="utf-8") as f:
    MAPPING = json.load(f)

SHOPIFY_TAXONOMY = {
    "Дивани / Прямі дивани": "fr-22",
    "Дивани / Кутові дивани": "fr-22-3",
    "Дивани / Модульні дивани": "fr-22-6",
    "Дивани / Розкладні дивани": "fr-22-7",
    "Дивани / Нерозкладні дивани": "fr-22",
    "Дивани / Офісні дивани": "fr-22",
    "Ліжка / Двоспальні ліжка": "fr-2-2",
    "Ліжка / Односпальні ліжка": "fr-2-2",
    "Ліжка / М'які ліжка": "fr-2-2",
    "Ліжка / Дерев'яні ліжка": "fr-2-2",
    "Ліжка / Дитячі ліжка": "fr-1-6",
    "Ліжка / Півтораспальні ліжка": "fr-2-2",
    "Ліжка / Кутові ліжка": "fr-2-2",
    "Матраци та аксесуари для сну / Безпружинні матраци": "fr-2-6",
    "Матраци та аксесуари для сну / Матраци Pocket Spring": "fr-2-6-3",
    "Матраци та аксесуари для сну / Матраци Боннель": "fr-2-6-3",
    "Матраци та аксесуари для сну / Матраци в дитячі ліжка": "fr-2-6-8",
    "Матраци та аксесуари для сну / Матраци на диван": "fr-2-6",
    "Матраци та аксесуари для сну / Наматрасники": "hg-15-1-12",
    "Матраци та аксесуари для сну / Подушки": "hg-15-1-9",
    "Матраци та аксесуари для сну / Ковдри": "hg-15-1-4",
    "Крісла / М'які крісла": "fr-7-1",
    "Крісла / Обідні крісла": "fr-7-9",
    "Столи / Журнальні столики і консолі": "fr-24-1",
    "Столи / Обідні столи": "fr-24-4",
    "Стільці / Обідні стільці": "fr-7-9",
    "Стільці / Барні стільці": "fr-7-12",
    "Стільці / Напівбарні стільці": "fr-7-12",
    "Стільці / Стільці з підлокітниками": "fr-7-1",
    "Пуфи та лавки / Пуфи": "fr-14",
    "Пуфи та лавки / Столики-пуфи": "fr-14",
    "Пуфи та лавки / Лавки": "fr-3",
    "Тумби та зберігання / Тумбочки": "fr-24-6",
    "Тумби та зберігання / Приліжкові тумби": "fr-24-6",
    "Тумби та зберігання / Комоди": "fr-4-5",
    "Садові та вуличні меблі / Садові меблі": "fr-15-2",
    "Садові та вуличні меблі / Шезлонги": "fr-15-4-5",
    "Садові та вуличні меблі / Вуличні дивани": "fr-15-4-4",
    "Садові та вуличні меблі / Крісла на вулицю": "fr-15-4-2",
    "Меблі для закладів / Дивани": "fr-22",
    "Меблі для закладів / Крісла": "fr-7-1",
    "Меблі для закладів / Пуфи": "fr-14",
    "Меблі для закладів / Лавки": "fr-3",
    "Без категорії": "fr",
}

OPT_TAGS = ['fabric', 'leg_color', 'frame_color', 'sleep_size', 'mechanism',
            'pillows', 'back_fabric', 'mattress_included', 'material',
            'modules', 'dimensions', 'tabletop_size',
            'height_opt', 'length_opt', 'width_opt']

AKORD_URL = os.environ["AKORD_CSV"]
WOODMAN_URL = os.environ["WOODMAN_CSV"]
VETRO_URL = os.environ["VETRO_XML"]
COMEFOR_URL = os.environ["COMEFOR_XML"]

def fetch_text(url):
    r = requests.get(url, timeout=30)
    r.encoding = "utf-8"
    return r.text

def clean_price(val):
    try:
        cleaned = str(val).replace(",", "").replace(" ", "").strip()
        return f"{float(cleaned):.2f}" if cleaned else "0.00"
    except (ValueError, TypeError):
        return "0.00"

def map_category(source, cat):
    mapped = MAPPING[source].get(cat)
    if not mapped:
        with open("unmapped.log", "a", encoding="utf-8") as f:
            f.write(f"{source}: {cat}\n")
        return "Без категорії"
    return mapped

def parse_akord(url):
    """Читає новий файл з плоскими option полями і колонками category/Images"""
    products = []
    text = fetch_text(url)
    reader = csv.DictReader(StringIO(text))
    seen = set()
    for row in reader:
        sku = str(row.get("Sku", "")).strip()
        if sku in seen:
            continue
        seen.add(sku)

        # Зображення
        images_raw = row.get("variant_image", "") or row.get("Images", "") or ""
        images = [i.strip() for i in images_raw.split(",") if i.strip()]

        # Категорія — вже є в файлі
        category = str(row.get("category", "") or "").strip() or "Без категорії"
        shopify_cat = str(row.get("shopify_category", "") or "").strip()
        if not shopify_cat:
            shopify_cat = SHOPIFY_TAXONOMY.get(category, "fr")

        # Плоскі option поля
        opts = {}
        for tag in OPT_TAGS:
            val = str(row.get(tag, "") or "").strip()
            if val and val.lower() != 'nan':
                opts[tag] = val

        products.append({
            "source": "akord",
            "sku": sku,
            "name": row.get("Name", ""),
            "price": clean_price(row.get("variant_price", "") or row.get("Price", "")),
            "category": category,
            "shopify_category": shopify_cat,
            "images": images,
            "description": row.get("ShortDescription", ""),
            "available": str(row.get("IsAvailable", "")).strip() == "Available",
            "vendor": "ВНД",
            "instock": str(row.get("InStock", "") or ""),
            "barcode": str(row.get("Barcode", "") or ""),
            "meta_title": str(row.get("MetaTitle", "") or ""),
            "meta_description": str(row.get("MetaDescription", "") or ""),
            "meta_keywords": str(row.get("MetaKeywords", "") or ""),
            "opts": opts,
        })
    return products

def parse_woodman(url):
    products = []
    text = fetch_text(url)
    reader = csv.DictReader(StringIO(text))
    next(reader)
    for row in reader:
        cat_raw = row.get("categories", "").strip().lower()
        mapped = map_category("woodman", cat_raw)
        photo = row.get("photo", "").strip()
        products.append({
            "source": "woodman", "sku": row.get("sku", ""),
            "name": row.get("name", ""),
            "price": clean_price(row.get("rrp_price", "")),
            "category": mapped,
            "shopify_category": SHOPIFY_TAXONOMY.get(mapped, "fr"),
            "images": [photo] if photo else [],
            "description": row.get("description", ""),
            "available": True, "vendor": "Woodman",
            "instock": "", "barcode": "",
            "meta_title": "", "meta_description": "", "meta_keywords": "",
            "opts": {},
        })
    return products

def parse_vetro(url):
    products = []
    text = fetch_text(url)
    root = ET.fromstring(text.encode("utf-8"))
    offers = root.find("shop").find("offers")
    for offer in offers:
        cat_id = offer.findtext("categoryId", "").strip()
        mapped = map_category("vetro", cat_id)
        pics = [p.text for p in offer.findall("picture") if p.text]
        desc_el = offer.find("description")
        products.append({
            "source": "vetro",
            "sku": offer.findtext("vendorCode", offer.get("id", "")),
            "name": offer.findtext("name", ""),
            "price": clean_price(offer.findtext("price", "")),
            "category": mapped,
            "shopify_category": SHOPIFY_TAXONOMY.get(mapped, "fr"),
            "images": pics,
            "description": desc_el.text if desc_el is not None else "",
            "available": offer.get("available") == "true",
            "vendor": offer.findtext("vendor", "Vetro"),
            "instock": "", "barcode": "",
            "meta_title": "", "meta_description": "", "meta_keywords": "",
            "opts": {},
        })
    return products

def parse_comefor(url):
    products = []
    text = fetch_text(url)
    root = ET.fromstring(text.encode("utf-8"))
    for item in root.find("items"):
        cat_id = item.findtext("categoryId", "").strip()
        mapped = map_category("comefor", cat_id)
        pics = [p.text for p in item.findall("picture") if p.text]
        products.append({
            "source": "comefor",
            "sku": item.findtext("sku", ""),
            "name": item.findtext("name", ""),
            "price": clean_price(item.findtext("priceuah", "0")),
            "category": mapped,
            "shopify_category": SHOPIFY_TAXONOMY.get(mapped, "fr"),
            "images": pics, "description": "",
            "available": item.findtext("stock", "") == "В наличии",
            "vendor": "Come-For",
            "instock": "", "barcode": "",
            "meta_title": "", "meta_description": "", "meta_keywords": "",
            "opts": {},
        })
    return products

def build_xml(products):
    catalog = ET.Element("catalog")
    for p in products:
        item = ET.SubElement(catalog, "item")
        ET.SubElement(item, "sku").text = str(p["sku"])
        ET.SubElement(item, "name").text = str(p["name"])
        ET.SubElement(item, "variant_price").text = str(p["price"])
        ET.SubElement(item, "vendor").text = str(p["vendor"])
        ET.SubElement(item, "category").text = p["category"]
        ET.SubElement(item, "shopify_id").text = p["shopify_category"]
        ET.SubElement(item, "available").text = "true" if p["available"] else "false"
        ET.SubElement(item, "instock").text = str(p.get("instock", "") or "")
        ET.SubElement(item, "barcode").text = str(p.get("barcode", "") or "")
        ET.SubElement(item, "meta_title").text = str(p.get("meta_title", "") or "")
        ET.SubElement(item, "meta_description").text = str(p.get("meta_description", "") or "")
        ET.SubElement(item, "meta_keywords").text = str(p.get("meta_keywords", "") or "")
        ET.SubElement(item, "description").text = str(p["description"] or "")
        for tag in OPT_TAGS:
            ET.SubElement(item, tag).text = str(p["opts"].get(tag, "") or "")
        first_img = p["images"][0] if p["images"] else ""
        ET.SubElement(item, "variant_image").text = first_img
        images_el = ET.SubElement(item, "images")
        for img in p["images"]:
            ET.SubElement(images_el, "image").text = img
    raw = ET.tostring(catalog, encoding="unicode")
    parsed = minidom.parseString(raw)
    return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

def main():
    print("Завантажую Акорд...")
    akord = parse_akord(AKORD_URL)
    print(f"  {len(akord)} товарів")
    print("Завантажую Woodman...")
    woodman = parse_woodman(WOODMAN_URL)
    print(f"  {len(woodman)} товарів")
    print("Завантажую Vetro...")
    vetro = parse_vetro(VETRO_URL)
    print(f"  {len(vetro)} товарів")
    print("Завантажую Come-For...")
    comefor = parse_comefor(COMEFOR_URL)
    print(f"  {len(comefor)} товарів")
    all_products = akord + woodman + vetro + comefor
    print(f"\nВсього товарів: {len(all_products)}")
    os.makedirs("output", exist_ok=True)
    with open("output/feed.xml", "w", encoding="utf-8") as f:
        f.write(build_xml(all_products))
    print("Готово → output/feed.xml")

if __name__ == "__main__":
    main()
