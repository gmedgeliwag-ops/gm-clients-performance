import csv, json, re, sys, urllib.request
from collections import defaultdict
from datetime import datetime, timezone

BASE = "https://docs.google.com/spreadsheets/d/e/2PACX-1vR4AFGR0APhVT7Ck29SXgz6WcrANmGuoesiXfLJ-09Ffd61o6g3mvOxOyZDeYxC_JF0ReFWyVM-ncne/pub"

GIDS = {
    "M&K": "312161458",
    "M&J": "1874373318",
    "SIC": "212039823",
    "peakCo": "1115357442",
    "MLC": "1403982598",
    "Elriz": "2092048495",
}

REGION_MAP = {
    "Metro Manila": "NCR",
    "Luzon": "Luzon",
    "Visayas": "Visayas",
    "Mindanao": "Mindanao",
}
REGIONS_ORDER = ["NCR", "Luzon", "Visayas", "Mindanao"]

SHIPMENT_STATUSES = {"Shipped", "Returning", "Returned", "Returned (fee)", "Delivered"}
RTS_STATUSES = {"Returned", "Returned (fee)", "Returning"}


def num(v):
    v = (v or "").strip()
    if not v:
        return 0.0
    try:
        return float(v)
    except ValueError:
        return 0.0


def fetch_rows(gid):
    url = f"{BASE}?gid={gid}&single=true&output=csv"
    with urllib.request.urlopen(url, timeout=60) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    return csv.DictReader(text.splitlines())


def pct(n, d):
    return round(n / d * 100, 2) if d else 0.0


result = {"companies": {}}
overall_sales = 0.0
overall_shipments = 0
overall_delivered = 0
overall_rts = 0

for company, gid in GIDS.items():
    total_sales = 0.0
    total_shipments = 0
    delivered_count = 0
    rts_count = 0
    product_sales = defaultdict(float)

    # (region, product) -> counters
    rp_orders = defaultdict(int)
    rp_delivered = defaultdict(int)
    rp_rts = defaultdict(int)
    rp_sales = defaultdict(float)

    reader = fetch_rows(gid)
    for row in reader:
        status = (row.get("Status") or "").strip()
        tracking = (row.get("Tracking number") or "").strip()
        if not tracking or status not in SHIPMENT_STATUSES:
            continue

        total_shipments += 1
        region_raw = (row.get("By region") or "").strip()
        region = REGION_MAP.get(region_raw)
        product = (row.get("Product name") or "Unknown").strip()

        if region:
            rp_orders[(region, product)] += 1

        if status == "Delivered":
            delivered_count += 1
            price = num(row.get("Unit price"))
            total_sales += price
            product_sales[product] += price
            if region:
                rp_delivered[(region, product)] += 1
                rp_sales[(region, product)] += price
        elif status in RTS_STATUSES:
            rts_count += 1
            if region:
                rp_rts[(region, product)] += 1

    delivery_pct = pct(delivered_count, total_shipments)
    rts_pct = pct(rts_count, total_shipments)

    top5_products = sorted(product_sales.items(), key=lambda x: -x[1])[:5]

    top5_by_region = {}
    for r in REGIONS_ORDER:
        candidates = [(p, s) for (reg, p), s in rp_sales.items() if reg == r]
        top5 = sorted(candidates, key=lambda x: -x[1])[:5]
        items = []
        for p, s in top5:
            orders = rp_orders[(r, p)]
            delivered = rp_delivered[(r, p)]
            rts = rp_rts[(r, p)]
            items.append({
                "name": p,
                "sales": round(s, 2),
                "orders": orders,
                "delivery_pct": pct(delivered, orders),
                "rts_pct": pct(rts, orders),
            })
        top5_by_region[r] = items

    result["companies"][company] = {
        "total_sales": round(total_sales, 2),
        "total_shipments": total_shipments,
        "delivered_count": delivered_count,
        "rts_count": rts_count,
        "delivery_pct": delivery_pct,
        "rts_pct": rts_pct,
        "top5_products": [{"name": n, "sales": round(v, 2)} for n, v in top5_products],
        "top5_by_region": top5_by_region,
    }

    overall_sales += total_sales
    overall_shipments += total_shipments
    overall_delivered += delivered_count
    overall_rts += rts_count

    print(f"{company}: shipments={total_shipments} sales={total_sales:.0f} delivery%={delivery_pct} rts%={rts_pct}", file=sys.stderr)

result["overview"] = {
    "total_sales": round(overall_sales, 2),
    "total_shipments": overall_shipments,
    "delivered_count": overall_delivered,
    "rts_count": overall_rts,
    "delivery_pct": pct(overall_delivered, overall_shipments),
    "rts_pct": pct(overall_rts, overall_shipments),
}
result["generated_at"] = datetime.now(timezone.utc).isoformat()

out_path = sys.argv[1] if len(sys.argv) > 1 else "data.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print("wrote", out_path, file=sys.stderr)
