import csv, json, sys, urllib.request
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


DATE_FORMATS = ("%B %d, %Y", "%d/%m/%Y", "%Y-%m-%d")


def parse_date(v):
    v = (v or "").strip()
    if not v:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def fetch_rows(gid):
    url = f"{BASE}?gid={gid}&single=true&output=csv"
    with urllib.request.urlopen(url, timeout=60) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    return csv.DictReader(text.splitlines())


result = {"companies": {}}

for company, gid in GIDS.items():
    # date -> {orders, delivered, rts, sales}
    daily = defaultdict(lambda: {"orders": 0, "delivered": 0, "rts": 0, "sales": 0.0})
    # (date, region, product) -> {orders, delivered, rts, sales}
    rpd = defaultdict(lambda: {"orders": 0, "delivered": 0, "rts": 0, "sales": 0.0})

    reader = fetch_rows(gid)
    n_rows = 0
    for row in reader:
        status = (row.get("Status") or "").strip()
        tracking = (row.get("Tracking number") or "").strip()
        if not tracking or status not in SHIPMENT_STATUSES:
            continue
        date = parse_date(row.get("Day created"))
        if date is None:
            continue

        n_rows += 1
        is_delivered = status == "Delivered"
        is_rts = status in RTS_STATUSES
        price = num(row.get("Unit price")) if is_delivered else 0.0

        d = daily[date]
        d["orders"] += 1
        if is_delivered:
            d["delivered"] += 1
            d["sales"] += price
        elif is_rts:
            d["rts"] += 1

        region_raw = (row.get("By region") or "").strip()
        region = REGION_MAP.get(region_raw)
        if region:
            product = (row.get("Product name") or "Unknown").strip()
            rp = rpd[(date, region, product)]
            rp["orders"] += 1
            if is_delivered:
                rp["delivered"] += 1
                rp["sales"] += price
            elif is_rts:
                rp["rts"] += 1

    daily_list = [
        {"date": date, "orders": v["orders"], "delivered": v["delivered"], "rts": v["rts"], "sales": round(v["sales"], 2)}
        for date, v in sorted(daily.items())
    ]
    rpd_list = [
        {"date": date, "region": region, "product": product,
         "orders": v["orders"], "delivered": v["delivered"], "rts": v["rts"], "sales": round(v["sales"], 2)}
        for (date, region, product), v in sorted(rpd.items())
    ]

    result["companies"][company] = {"daily": daily_list, "region_product_daily": rpd_list}
    print(f"{company}: rows={n_rows} daily_buckets={len(daily_list)} region_product_buckets={len(rpd_list)}", file=sys.stderr)

result["generated_at"] = datetime.now(timezone.utc).isoformat()

out_path = sys.argv[1] if len(sys.argv) > 1 else "data.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(result, f, separators=(",", ":"), ensure_ascii=False)

print("wrote", out_path, file=sys.stderr)
