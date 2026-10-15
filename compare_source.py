"""Порівняння ВНД-джерела фіда (секрет AKORD_CSV) з посиланням CMP_URL. Лише діагностика."""
import csv, os, collections
from io import StringIO
import requests

def load(url):
    r = requests.get(url, timeout=120); r.raise_for_status(); r.encoding = "utf-8"
    return list(csv.DictReader(StringIO(r.text)))

a_url, b_url = os.environ["AKORD_CSV"], os.environ["CMP_URL"]
print("COMPARE same URL:", a_url.strip() == b_url.strip())
A, B = load(a_url), load(b_url)
print(f"COMPARE rows: feed-source={len(A)} sheet={len(B)}")
key = lambda r: (str(r.get("Sku", "")).strip(), str(r.get("Alias", "")).strip(), str(r.get("fabric", "")), str(r.get("leg_color", "")), str(r.get("sleep_size", "")))
ka, kb = {key(r): r for r in A}, {key(r): r for r in B}
print("COMPARE only in feed-source:", len(set(ka) - set(kb)), "| only in sheet:", len(set(kb) - set(ka)))
for tag, keys, src in (("ONLY_FEED", set(ka) - set(kb), ka), ("ONLY_SHEET", set(kb) - set(ka), kb)):
    c = collections.Counter((src[k].get("Name"), src[k].get("Alias")) for k in keys)
    for (n, al), v in c.most_common(40):
        print(f"COMPARE {tag}: {n} | {al} | {v}")
diff = collections.Counter()
for k in set(ka) & set(kb):
    for col in ("Name", "price", "Alias", "IsAvailable", "category", "InStock"):
        if str(ka[k].get(col, "")).strip() != str(kb[k].get(col, "")).strip():
            diff[(col, str(ka[k].get(col, ""))[:40], str(kb[k].get(col, ""))[:40])] += 1
print("COMPARE changed fields:", sum(diff.values()))
for (col, x, y), v in diff.most_common(40):
    print(f"COMPARE DIFF {col}: feed='{x}' sheet='{y}' x{v}")
c = collections.Counter()
for r in A:
    n = r.get("Name", "")
    if any(x in n for x in ("Прованс", "JORD", "Дрім", "DREAM", "Лора", "Ґрейс", "Флора")):
        c[(n, r.get("Alias", ""), r.get("category", ""))] += 1
for (n, al, cat), v in sorted(c.items()):
    print(f"COMPARE NAMES: {n} | {al} | {cat} | {v}")
