"""Доповнює виправлену таблицю ВНД даними з вигрузки сайту (export-*.csv, роздільник «;») за SKU
і прибирає повні дублікати (однакові опції та ціна). Запуск: python tools/merge_export.py clean.csv export.csv out.csv"""
import csv, os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import process as P

clean, export, out = sys.argv[1:4]
rd = csv.DictReader(open(clean, encoding="utf-8-sig"))
cols, rows = rd.fieldnames, list(rd)
E = {r["Sku"]: r for r in csv.DictReader(open(export, encoding="utf-8-sig"), delimiter=";")}
g = lambda r, k: str(r.get(k, "") or "").strip()

# атрибут сайту -> колонка таблиці
MAP = {"Конфігурація": "modules", "ВИСОТА, см": "height_opt", "ШИРИНА, см": "width_opt", "ДОВЖИНА, см": "length_opt"}
filled = collections.Counter()
for r in rows:
    e = E.get(g(r, "Sku"))
    if not e:
        continue
    for src, dst in MAP.items():
        v = g(e, src)
        if v and not g(r, dst):
            r[dst] = v
            filled[(r["Name"], dst)] += 1

# повні дублікати: той самий товар, ті самі значення всіх опцій і та сама ціна
tags = P.AKORD_PRICE_OPTS + [t for t in P.AKORD_OPT_LABELS if t not in P.AKORD_PRICE_OPTS]
seen, kept, dropped = set(), [], collections.Counter()
for r in rows:
    k = (g(r, "Alias"), tuple(g(r, t) for t in tags), P.clean_price(g(r, "price")))
    if k in seen:
        dropped[r["Name"]] += 1
        continue
    seen.add(k)
    kept.append(r)

with open(out, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(kept)
print("заповнено:", dict(filled))
print("прибрано дублікатів:", dict(dropped), "→ рядків", len(kept))
left = collections.defaultdict(list)
for r in kept:
    left[(g(r, "Alias"), tuple(g(r, t) for t in tags))].append(r)
bad = collections.Counter()
for (al, _), rs in left.items():
    if len(rs) > 1:
        bad[rs[0]["Name"]] += len(rs)
print("ще з однаковими опціями, але різними цінами:", dict(bad))
