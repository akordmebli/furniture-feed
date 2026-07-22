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
    "Дивани / Прямі дивани": "Furniture > Sofas",
    "Дивани / Кутові дивани": "Furniture > Sofas > Corner Sofas",
    "Дивани / Модульні дивани": "Furniture > Sofas > Sectional Sofas",
    "Дивани / Розкладні дивани": "Furniture > Sofas > Sofa Beds",
    "Дивани / Нерозкладні дивани": "Furniture > Sofas",
    "Дивани / Офісні дивани": "Furniture > Sofas",
    "Ліжка / Двоспальні ліжка": "Furniture > Beds & Accessories > Beds & Bed Frames",
    "Ліжка / Односпальні ліжка": "Furniture > Beds & Accessories > Beds & Bed Frames",
    "Ліжка / М'які ліжка": "Furniture > Beds & Accessories > Beds & Bed Frames",
    "Ліжка / Дерев'яні ліжка": "Furniture > Beds & Accessories > Beds & Bed Frames",
    "Ліжка / Дитячі ліжка": "Furniture > Baby & Toddler Furniture > Cribs & Toddler Beds",
    "Ліжка / Півтораспальні ліжка": "Furniture > Beds & Accessories > Beds & Bed Frames",
    "Ліжка / Кутові ліжка": "Furniture > Beds & Accessories > Beds & Bed Frames",
    "Матраци та аксесуари для сну / Безпружинні матраци": "Furniture > Beds & Accessories > Mattresses",
    "Матраци та аксесуари для сну / Матраци Pocket Spring": "Furniture > Beds & Accessories > Mattresses > Innerspring Mattresses",
    "Матраци та аксесуари для сну / Матраци Боннель": "Furniture > Beds & Accessories > Mattresses > Innerspring Mattresses",
    "Матраци та аксесуари для сну / Матраци в дитячі ліжка": "Furniture > Beds & Accessories > Mattresses > Crib & Toddler Mattresses",
    "Матраци та аксесуари для сну / Матраци на диван": "Furniture > Beds & Accessories > Mattresses",
    "Матраци та аксесуари для сну / Наматрасники": "Furniture > Beds & Accessories > Mattress Toppers",
    "Матраци та аксесуари для сну / Подушки": "Home & Garden > Linens & Bedding > Bedding > Pillows",
    "Матраци та аксесуари для сну / Ковдри": "Home & Garden > Linens & Bedding > Bedding > Blankets",
    "Крісла / М'які крісла": "Furniture > Chairs > Armchairs, Recliners & Sleeper Chairs",
    "Крісла / Обідні крісла": "Furniture > Chairs > Kitchen & Dining Room Chairs",
    "Столи / Журнальні столики і консолі": "Furniture > Tables > Accent Tables",
    "Столи / Обідні столи": "Furniture > Tables > Kitchen & Dining Room Tables",
    "Стільці / Обідні стільці": "Furniture > Chairs > Kitchen & Dining Room Chairs",
    "Стільці / Барні стільці": "Furniture > Chairs > Table & Bar Stools",
    "Стільці / Напівбарні стільці": "Furniture > Chairs > Table & Bar Stools",
    "Стільці / Стільці з підлокітниками": "Furniture > Chairs > Armchairs, Recliners & Sleeper Chairs",
    "Пуфи та лавки / Пуфи": "Furniture > Ottomans",
    "Пуфи та лавки / Столики-пуфи": "Furniture > Ottomans > Cocktail Ottomans",
    "Пуфи та лавки / Лавки": "Furniture > Benches",
    "Тумби та зберігання / Тумбочки": "Furniture > Tables > Nightstands",
    "Тумби та зберігання / Приліжкові тумби": "Furniture > Tables > Nightstands",
    "Тумби та зберігання / Комоди": "Furniture > Cabinets & Storage > Dressers",
    "Садові та вуличні меблі / Садові меблі": "Furniture > Outdoor Furniture > Outdoor Furniture Sets",
    "Садові та вуличні меблі / Шезлонги": "Furniture > Outdoor Furniture > Outdoor Seating > Sunloungers",
    "Садові та вуличні меблі / Вуличні дивани": "Furniture > Outdoor Furniture > Outdoor Seating > Outdoor Sofas",
    "Садові та вуличні меблі / Крісла на вулицю": "Furniture > Outdoor Furniture > Outdoor Seating > Outdoor Chairs",
    "Меблі для закладів / Дивани": "Furniture > Sofas",
    "Меблі для закладів / Крісла": "Furniture > Chairs > Armchairs, Recliners & Sleeper Chairs",
    "Меблі для закладів / Пуфи": "Furniture > Ottomans",
    "Меблі для закладів / Лавки": "Furniture > Benches",
    "Без категорії": "Furniture",
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
    products = []
    text = fetch_text(url)
    reader = csv.DictReader(StringIO(text))
    seen = set()
    for row in reader:
        sku = row.get("Sku", "").strip()
        if sku in seen:
            continue
        seen.add(sku)
        raw_cats = row.get("Categories", "")
        cats = [c.strip() for c in raw_cats.split(";") if c.strip()]
        mapped = map_category("akord", cats[0]) if cats else "Без категорії"
        images = [i.strip() for i in row.get("Images", "").split(",") if i.strip()]
        products.append({
            "source": "akord", "id": row.get("ID", ""), "sku": sku,
            "name": row.get("Name", ""), "price": clean_price(row.get("Price", "")),
            "currency": "UAH", "category": mapped,
            "shopify_category": SHOPIFY_TAXONOMY.get(mapped, "Furniture"),
            "images": images, "description": row.get("ShortDescription", ""),
            "available": row.get("IsAvailable", "") == "Available",
            "vendor": row.get("Vendor", ""),
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
            "shopify_category": SHOPIFY_TAXONOMY.get(mapped, "Furniture"),
            "images": [photo] if photo else [], "description": row.get("description", ""),
            "available": True, "vendor": "Woodman",
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
            "shopify_category": SHOPIFY_TAXONOMY.get(mapped, "Furniture"),
            "images": pics, "description": desc_el.text if desc_el is not None else "",
            "available": offer.get("available") == "true",
            "vendor": offer.findtext("vendor", "Vetro"),
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
            "shopify_category": SHOPIFY_TAXONOMY.get(mapped, "Furniture"),
            "images": pics, "description": "",
            "available": item.findtext("stock", "") == "В наличии",
            "vendor": "Come-For",
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
