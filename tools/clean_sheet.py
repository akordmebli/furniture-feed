"""Робить із вигрузки ВНД чисту таблицю: ті самі колонки, але з виправленими аліасами, фото, значеннями і порядком.
Запуск: python tools/clean_sheet.py вхідний.csv вихідний.csv"""
import csv, os, re, sys, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import process as P

src, dst = sys.argv[1], sys.argv[2]
rd = csv.DictReader(open(src, encoding="utf-8"))
cols = rd.fieldnames
rows = list(rd)
g = lambda r, k: str(r.get(k, "") or "")

# 1) аліаси: явні виправлення, потім унікальні (перша назва лишає alias)
first_img = {}
for r in rows:
    if P.clean_images(g(r, "image")):
        first_img.setdefault(g(r, "Alias"), g(r, "image"))
for r in rows:
    if not P.clean_images(g(r, "image")):
        r["image"] = first_img.get(g(r, "Alias"), "")
img_by_alias = {}
for r in rows:
    img_by_alias.setdefault(g(r, "Alias"), g(r, "image"))
for r in rows:
    fix = P.ALIAS_FIXES.get((g(r, "Alias"), P.clean_text(g(r, "Name"))))
    if fix:
        r["Alias"] = fix
        r["image"] = img_by_alias.get(fix, g(r, "image"))
owner = {}
for r in rows:
    owner.setdefault(g(r, "Alias"), P.clean_text(g(r, "Name")))
for r in rows:
    nm = P.clean_text(g(r, "Name"))
    if owner[g(r, "Alias")] != nm:
        r["Alias"] = f'{g(r, "Alias")}-{P.slug(nm)}'

for r in rows:
    r["Name"] = P.clean_text(g(r, "Name"))
    # 2) значення характеристик
    for tag in P.OPT_TAGS:
        if g(r, tag).strip():
            r[tag] = P.norm_size_value(tag, g(r, tag).strip())
    if g(r, "Alias") in P.NO_SLEEP_ALIASES:
        r["sleep_size"] = ""
    # 3) фото
    imgs = P.clean_images(g(r, "image"))
    if "JORD" in r["Name"].upper() and "ROSET" in g(r, "image").upper():
        imgs = list(P.JORD_IMAGES)
    r["image"] = ", ".join(imgs)
    # 4) тексти
    for k in ("ShortDescription", "MetaTitle", "MetaDescription", "MetaKeywords"):
        r[k] = P.brand_fix(P.clean_text(g(r, k)) if k == "ShortDescription" else g(r, k))

# 5) порядок: товари як були, варіанти — від меншого до більшого
order = {}
for r in rows:
    order.setdefault(g(r, "Alias"), len(order))
tags = P.AKORD_PRICE_OPTS + [t for t in P.AKORD_OPT_LABELS if t not in P.AKORD_PRICE_OPTS]
rows.sort(key=lambda r: (order[g(r, "Alias")], [P.natural_key(t, g(r, t)) for t in tags]))

with open(dst, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)

# 6) що лишилось для ручного розгляду
print(f"рядків: {len(rows)}, товарів: {len(order)}")
combos = collections.defaultdict(list)
for r in rows:
    combos[(g(r, "Alias"), tuple(g(r, t) for t in tags))].append(r)
dups = collections.Counter()
for (al, _), rs in combos.items():
    if len(rs) > 1:
        dups[(al, rs[0]["Name"])] += len(rs)
print("\nОДНАКОВІ ВАРІАНТИ (потрібно розрізнити характеристикою):")
for (al, nm), n in sorted(dups.items()):
    print(f"  {nm} [{al}]: {n} рядків у повторах")
print("\nБЕЗ ФОТО:", sorted({(r['Name']) for r in rows if not r['image']}))
print("БЕЗ ЦІНИ:", sorted({r['Name'] for r in rows if P.clean_price(g(r, 'price')) == '0.00'}))
print("УСЬОГО згадок VINADI:", sum(len(re.findall('(?i)vinadi', g(r, 'ShortDescription') + g(r, 'MetaDescription'))) for r in rows))
