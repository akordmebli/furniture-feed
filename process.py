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
    "Дивани / Прямі дивани": "gid://shopify/TaxonomyCategory/fr-22",
    "Дивани / Кутові дивани": "gid://shopify/TaxonomyCategory/fr-22-3",
    "Дивани / Модульні дивани": "gid://shopify/TaxonomyCategory/fr-22-6",
    "Дивани / Розкладні дивани": "gid://shopify/TaxonomyCategory/fr-22-7",
    "Дивани / Нерозкладні дивани": "gid://shopify/TaxonomyCategory/fr-22",
    "Дивани / Офісні дивани": "gid://shopify/TaxonomyCategory/fr-22",
    "Ліжка / Двоспальні ліжка": "gid://shopify/TaxonomyCategory/fr-2-2",
    "Ліжка / Односпальні ліжка": "gid://shopify/TaxonomyCategory/fr-2-2",
    "Ліжка / М'які ліжка": "gid://shopify/TaxonomyCategory/fr-2-2",
    "Ліжка / Дерев'яні ліжка": "gid://shopify/TaxonomyCategory/fr-2-2",
    "Ліжка / Дитячі ліжка": "gid://shopify/TaxonomyCategory/fr-1-6",
    "Ліжка / Півтораспальні ліжка": "gid://shopify/TaxonomyCategory/fr-2-2",
    "Ліжка / Кутові ліжка": "gid://shopify/TaxonomyCategory/fr-2-2",
    "Матраци та аксесуари для сну / Безпружинні матраци": "gid://shopify/TaxonomyCategory/fr-2-6",
    "Матраци та аксесуари для сну / Матраци Pocket Spring": "gid://shopify/TaxonomyCategory/fr-2-6-3",
    "Матраци та аксесуари для сну / Матраци Боннель": "gid://shopify/TaxonomyCategory/fr-2-6-3",
    "Матраци та аксесуари для сну / Матраци в дитячі ліжка": "gid://shopify/TaxonomyCategory/fr-2-6-8",
    "Матраци та аксесуари для сну / Матраци на диван": "gid://shopify/TaxonomyCategory/fr-2-6",
    "Матраци та аксесуари для сну / Наматрасники": "gid://shopify/TaxonomyCategory/hg-15-1-12",
    "Матраци та аксесуари для сну / Подушки": "gid://shopify/TaxonomyCategory/hg-15-1-9",
    "Матраци та аксесуари для сну / Ковдри": "gid://shopify/TaxonomyCategory/hg-15-1-4",
    "Крісла / М'які крісла": "gid://shopify/TaxonomyCategory/fr-7-1",
    "Крісла / Обідні крісла": "gid://shopify/TaxonomyCategory/fr-7-9",
    "Столи / Журнальні столики і консолі": "gid://shopify/TaxonomyCategory/fr-24-1",
    "Столи / Обідні столи": "gid://shopify/TaxonomyCategory/fr-24-4",
    "Стільці / Обідні стільці": "gid://shopify/TaxonomyCategory/fr-7-9",
    "Стільці / Барні стільці": "gid://shopify/TaxonomyCategory/fr-7-12",
    "Стільці / Напівбарні стільці": "gid://shopify/TaxonomyCategory/fr-7-12",
    "Стільці / Стільці з підлокітниками": "gid://shopify/TaxonomyCategory/fr-7-1",
    "Пуфи та лавки / Пуфи": "gid://shopify/TaxonomyCategory/fr-14",
    "Пуфи та лавки / Столики-пуфи": "gid://shopify/TaxonomyCategory/fr-14",
    "Пуфи та лавки / Лавки": "gid://shopify/TaxonomyCategory/fr-3",
    "Тумби та зберігання / Тумбочки": "gid://shopify/TaxonomyCategory/fr-24-6",
    "Тумби та зберігання / Приліжкові тумби": "gid://shopify/TaxonomyCategory/fr-24-6",
    "Тумби та зберігання / Комоди": "gid://shopify/TaxonomyCategory/fr-4-5",
    "Садові та вуличні меблі / Садові меблі": "gid://shopify/TaxonomyCategory/fr-15-2",
    "Садові та вуличні меблі / Шезлонги": "gid://shopify/TaxonomyCategory/fr-15-4-5",
    "Садові та вуличні меблі / Вуличні дивани": "gid://shopify/TaxonomyCategory/fr-15-4-4",
    "Садові та вуличні меблі / Крісла на вулицю": "gid://shopify/TaxonomyCategory/fr-15-4-2",
    "Меблі для закладів / Дивани": "gid://shopify/TaxonomyCategory/fr-22",
    "Меблі для закладів / Крісла": "gid://shopify/TaxonomyCategory/fr-7-1",
    "Меблі для закладів / Пуфи": "gid://shopify/TaxonomyCategory/fr-14",
    "Меблі для закладів / Лавки": "gid://shopify/TaxonomyCategory/fr-3",
    "Без категорії": "gid://shopify/TaxonomyCategory/fr",
}

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
    """Новий парсер — читає файл з усіма Option колонками як є"""
    products = []
    text = fetch_text(url)
    reader = csv.DictReader(StringIO(text))
    seen = set()
    for row in reader:
        sku = str(row.get("Sku", "")).strip()
        if sku in seen:
            continue
        seen.add(sku)
        raw_cats = row.get("Categories", "")
        cats = [c.strip() for c in raw_cats.split(";") if c.strip()]
        mapped = map_category("akord", cats[0]) if cats else "Без категорії"
        images = [i.strip() for i in row.get("Images", "").split(",") if i.strip()]

        # Збираємо всі Option поля
        options = {}
        for i in range(1, 16):
            options[f"Option{i} Name"] = row.get(f"Option{i} Name", "")
        for i in range(1, 16):
            options[f"Option{i} Value"] = row.get(f"Option{i} Value", "")

        products.append({
            "source": "akord",
            "id": row.get("ID", ""),
            "sku": sku,
            "name": row.get("Name", ""),
            "price": clean_price(row.get("Price", "")),
            "currency": "UAH",
            "category": mapped,
            "shopify_category": SHOPIFY_TAXONOMY.get(mapped, "gid://shopify/TaxonomyCategory/fr"),
            "images": images,
            "description": row.get("ShortDescription", ""),
            "available": row.get("IsAvailable", "") == "Available",
            "vendor": row.get("Vendor", ""),
            "options": options,
            # Розмірні поля
            "vysota": row.get("Висота, см", ""),
            "dovzhyna": row.get("Довжина, см", ""),
            "glybyna": row.get("Глибина сидіння, см", ""),
            "shyryna": row.get("Ширина, см", ""),
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
            "source": "woodman", "id": row.get("sku", ""), "sku": row.get("sku", ""),
            "name": row.get("name", ""), "price": clean_price(row.get("rrp_price", "")),
            "currency": "UAH", "category": mapped,
            "shopify_category": SHOPIFY_TAXONOMY.get(mapped, "gid://shopify/TaxonomyCategory/fr"),
            "images": [photo] if photo else [], "description": row.get("description", ""),
            "available": True, "vendor": "Woodman", "options": {}, 
            "vysota": "", "dovzhyna": "", "glybyna": "", "shyryna": "",
        })
    return products

def parse_vetro(url):
    products = []
    text = fetch_text(url)
    root = ET.fromstring(text.encode("utf-8"))
    shop = root.find("shop")
    offers = shop.find("offers")
    for offer in offers:
        cat_id = offer.findtext("categoryId", "").strip()
        mapped = map_category("vetro", cat_id)
        pics = [p.text for p in offer.findall("picture") if p.text]
        desc_el = offer.find("description")
        products.append({
            "source": "vetro", "id": offer.get("id", ""),
            "sku": offer.findtext("vendorCode", offer.get("id", "")),
            "name": offer.findtext("name", ""), "price": clean_price(offer.findtext("price", "")),
            "currency": "UAH", "category": mapped,
            "shopify_category": SHOPIFY_TAXONOMY.get(mapped, "gid://shopify/TaxonomyCategory/fr"),
            "images": pics, "description": desc_el.text if desc_el is not None else "",
            "available": offer.get("available") == "true",
            "vendor": offer.findtext("vendor", "Vetro"), "options": {},
            "vysota": "", "dovzhyna": "", "glybyna": "", "shyryna": "",
        })
    return products

def parse_comefor(url):
    products = []
    text = fetch_text(url)
    root = ET.fromstring(text.encode("utf-8"))
    items = root.find("items")
    for item in items:
        cat_id = item.findtext("categoryId", "").strip()
        mapped = map_category("comefor", cat_id)
        pics = [p.text for p in item.findall("picture") if p.text]
        products.append({
            "source": "comefor", "id": item.findtext("id", ""),
            "sku": item.findtext("sku", ""), "name": item.findtext("name", ""),
            "price": clean_price(item.findtext("priceuah", "0")),
            "currency": "UAH", "category": mapped,
            "shopify_category": SHOPIFY_TAXONOMY.get(mapped, "gid://shopify/TaxonomyCategory/fr"),
            "images": pics, "description": "",
            "available": item.findtext("stock", "") == "В наличии",
            "vendor": "Come-For", "options": {},
            "vysota": "", "dovzhyna": "", "glybyna": "", "shyryna": "",
        })
    return products

def build_xml(products):
    catalog = ET.Element("catalog")
    for p in products:
        item = ET.SubElement(catalog, "item")
        ET.SubElement(item, "id").text = str(p["id"])
        ET.SubElement(item, "sku").text = str(p["sku"])
        ET.SubElement(item, "name").text = str(p["name"])
        ET.SubElement(item, "price").text = str(p["price"])
        ET.SubElement(item, "currency").text = p["currency"]
        ET.SubElement(item, "category").text = p["category"]
        ET.SubElement(item, "shopify_category").text = p["shopify_category"]
        ET.SubElement(item, "vendor").text = str(p["vendor"])
        ET.SubElement(item, "available").text = "true" if p["available"] else "false"
        ET.SubElement(item, "description").text = str(p["description"] or "")
        # Розміри
        ET.SubElement(item, "vysota").text = str(p.get("vysota", "") or "")
        ET.SubElement(item, "dovzhyna").text = str(p.get("dovzhyna", "") or "")
        ET.SubElement(item, "glybyna").text = str(p.get("glybyna", "") or "")
        ET.SubElement(item, "shyryna").text = str(p.get("shyryna", "") or "")
        # Options
        options = p.get("options", {})
        if options:
            opts_el = ET.SubElement(item, "options")
            for i in range(1, 16):
                name_val = str(options.get(f"Option{i} Name", "") or "")
                value_val = str(options.get(f"Option{i} Value", "") or "")
                if name_val:
                    opt = ET.SubElement(opts_el, f"option{i}")
                    ET.SubElement(opt, "name").text = name_val
                    ET.SubElement(opt, "value").text = value_val
        # Images
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
    xml_content = build_xml(all_products)
    with open("output/feed.xml", "w", encoding="utf-8") as f:
        f.write(xml_content)
    print("Готово → output/feed.xml")

if __name__ == "__main__":
    main()
