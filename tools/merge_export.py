"""Доповнює виправлену таблицю ВНД даними з вигрузки сайту (export-*.csv, роздільник «;») за SKU.
Різні характеристики беруться з ProductModificationName («Товар, Категорія тканини: А, Механізм: ...»).
Рядки НЕ видаляються. Запуск: python tools/merge_export.py clean.csv export.csv out.csv"""
import csv, os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import process as P

clean, export, out = sys.argv[1:4]
rd = csv.DictReader(open(clean, encoding="utf-8-sig"))
cols, rows = rd.fieldnames, list(rd)
E = {r["Sku"]: r for r in csv.DictReader(open(export, encoding="utf-8-sig"), delimiter=";")}
g = lambda r, k: str(r.get(k, "") or "").strip()

COLUMN = {  # назва характеристики на сайті -> колонка таблиці
    "Категорія тканини": "fabric", "Колір ніжок": "leg_color", "Колір ніжки та дерев'яного декору": "leg_color",
    "Механізм": "mechanism", "Розмір спального місця": "sleep_size", "Розміри": "dimensions",
}
ATTR = {"Конфігурація": "modules", "ВИСОТА, см": "height_opt", "ШИРИНА, см": "width_opt", "ДОВЖИНА, см": "length_opt"}
filled, conflicts = collections.Counter(), []
for r in rows:
    e = E.get(g(r, "Sku"))
    if not e:
        continue
    pairs = {}
    for part in g(e, "ProductModificationName").split(",")[1:]:
        if ":" in part:
            k, v = part.split(":", 1)
            pairs[k.strip()] = v.strip()
    updates = {COLUMN[k]: v for k, v in pairs.items() if k in COLUMN}
    updates.update({dst: g(e, src) for src, dst in ATTR.items() if g(e, src)})
    for col, v in updates.items():
        v = P.norm_size_value(col, v)
        v = P.VALUE_FIXES.get(col, {}).get(v, v)
        if not v:
            continue
        if not g(r, col):
            r[col] = v
            filled[(r["Name"], col)] += 1
        elif g(r, col) != v:
            conflicts.append((r["Sku"], col, g(r, col), v))

with open(out, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)

print("заповнено:", dict(filled))
print("конфліктів значень:", len(conflicts), conflicts[:5])
tags = P.AKORD_PRICE_OPTS + [t for t in P.AKORD_OPT_LABELS if t not in P.AKORD_PRICE_OPTS]
left = collections.defaultdict(list)
for r in rows:
    left[(g(r, "Alias"), tuple(g(r, t) for t in tags))].append(r)
bad = collections.defaultdict(lambda: [0, 0])
for rs in left.values():
    if len(rs) > 1:
        b = bad[rs[0]["Name"]]
        b[0] += len(rs)
        b[1] += 0 if len({P.clean_price(g(x, "price")) for x in rs}) > 1 else 1
print("ще з однаковими опціями (рядків, з них з однаковою ціною):")
for n, (c, same) in sorted(bad.items()):
    print(f"  {n}: {c} рядків")
