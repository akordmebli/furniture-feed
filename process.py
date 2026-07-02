import os
import csv
import json
import requests
import xml.etree.ElementTree as ET
from io import StringIO

with open("mapping.json", encoding="utf-8") as f:
    MAPPING = json.load(f)

AKORD_URL = os.environ["AKORD_CSV"]
WOODMAN_URL = os.environ["WOODMAN_CSV"]
VETRO_URL = os.environ["VETRO_XML"]
COMEFOR_URL = os.environ["COMEFOR_XML"]

def fetch_text(url):
    r = requests.get(url, timeout=30)
    r.encoding = "utf-8"
    return r.text

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
        products.append({
            "source": "akord",
            "id": row.get("ID", ""),
            "sku": sku,
            "name": row.get("Name", ""),
            "price": row.get("Price", ""),
            "currency": "UAH",
            "category": mapped,
            "images": row.get("Images", ""),
            "description": row.get("ShortDescription", ""),
            "available": row.get("IsAvailable", ""),
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
        products.append({
            "source": "woodman",
            "id": row.get("sku", ""),
            "sku": row.get("sku", ""),
            "name": row.get("name", ""),
            "price": row.get("rrp_price", "").replace(",", ""),
            "currency": "UAH",
            "category": mapped,
            "images": row.get("photo", ""),
            "description": row.get("description", ""),
            "available": "Available",
            "vendor": "Woodman",
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
        name_el = offer.find("name")
        price_el = offer.find("price")
        pics = [p.text for p in offer.findall("picture") if p.text]
        desc_el = offer.find("description")
        products.append({
            "source": "vetro",
            "id": offer.get("id", ""),
            "sku": offer.findtext("vendorCode", offer.get("id", "")),
            "name": name_el.text if name_el is not None else "",
            "price": price_el.text if price_el is not None else "",
            "currency": "UAH",
            "category": mapped,
            "images": "; ".join(pics),
            "description": desc_el.text if desc_el is not None else "",
            "available": "Available" if offer.get("available") == "true" else "Unavailable",
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
        price_text = item.findtext("priceuah", "0")
        pics = [p.text for p in item.findall("picture") if p.text]
        products.append({
            "source": "comefor",
            "id": item.findtext("id", ""),
            "sku": item.findtext("sku", ""),
            "name": item.findtext("name", ""),
            "price": price_text,
            "currency": "UAH",
            "category": mapped,
            "images": "; ".join(pics),
            "description": "",
            "available": "Available" if item.findtext("stock", "") == "В наличии" else "Unavailable",
            "vendor": "Come-For",
        })
    return products

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

    fields = ["source","id","sku","name","price","currency","category","images","description","available","vendor"]
    with open("output/feed.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_products)

    print("Готово → output/feed.csv")

if __name__ == "__main__":
    os.makedirs("output", exist_ok=True)
    main()
