import csv, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime

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

DATE_FORMATS = ("%B %d, %Y", "%d/%m/%Y", "%Y-%m-%d")

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
BATCH_SIZE = 500


def num(v):
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


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


def build_rows(company, gid):
    rows = []
    last_date = None
    for i, row in enumerate(fetch_rows(gid)):
        order_id = (row.get("ID") or "").strip()
        tracking = (row.get("Tracking number") or "").strip()
        status = (row.get("Status") or "").strip()
        is_upsell = order_id == "_" and not tracking

        date = parse_date(row.get("Day created"))
        if date:
            last_date = date
        elif is_upsell:
            date = last_date

        if date is None:
            continue

        region_raw = (row.get("By region") or "").strip()
        region_norm = REGION_MAP.get(region_raw)
        is_shipment = bool(tracking) and status in SHIPMENT_STATUSES and not is_upsell
        is_delivered = is_shipment and status == "Delivered"
        is_rts = is_shipment and status in RTS_STATUSES
        rts_reason_norm = ((row.get("Return reason") or "").strip() or "Unspecified") if is_rts else None

        row_key = f"upsell-{i}" if is_upsell else (order_id or f"row-{i}")

        rows.append({
            "company": company,
            "row_key": row_key,
            "order_id": order_id or None,
            "tracking_number": tracking or None,
            "fee_paid_to_delivery": num(row.get("Fee paid to delivery co.")),
            "status": status or None,
            "assigning_seller": (row.get("Assigning seller") or "").strip() or None,
            "customer_care_staff": (row.get("Customer care staff") or "").strip() or None,
            "customer_name": (row.get("Customer") or "").strip() or None,
            "phone_number": (row.get("Phone number") or "").strip() or None,
            "commune_village": (row.get("Commune/Village") or "").strip() or None,
            "district": (row.get("District") or "").strip() or None,
            "province_city": (row.get("Province/City") or "").strip() or None,
            "day_created": date,
            "product_name": (row.get("Product name") or "").strip() or None,
            "unit_price": num(row.get("Unit price")),
            "total_price": num(row.get("Total price")),
            "ad_id": (row.get("Ad ID") or "").strip() or None,
            "date_sent_to_partner": (row.get("Date sending to the partner (Date)") or "").strip() or None,
            "marketer": (row.get("Marketer") or "").strip() or None,
            "return_reason": (row.get("Return reason") or "").strip() or None,
            "region_raw": region_raw or None,
            "region_norm": region_norm,
            "first_delivery": (row.get("First Delivery") or "").strip() or None,
            "order_delivered_date": (row.get("Order delivered date") or "").strip() or None,
            "order_returned_date": (row.get("Order returned date") or "").strip() or None,
            "customer_type": (row.get("New/Old customer") or "").strip() or None,
            "shipping_info": (row.get("Shipping info") or "").strip() or None,
            "item_handler": (row.get("Item handler") or "").strip() or None,
            "orders_source": (row.get("Orders sources") or "").strip() or None,
            "expected_delivery_date": (row.get("Expected delivery date") or "").strip() or None,
            "detail_address": (row.get("Detail address") or "").strip() or None,
            "warehouse": (row.get("Warehouse") or "").strip() or None,
            "variation_id": (row.get("Variation ID") or "").strip() or None,
            "promotion_id": (row.get("Promotion ID") or "").strip() or None,
            "is_upsell": is_upsell,
            "is_shipment": is_shipment,
            "is_delivered": is_delivered,
            "is_rts": is_rts,
            "rts_reason_norm": rts_reason_norm,
        })
    return rows


def upsert_batch(batch, attempts=3):
    url = f"{SUPABASE_URL}/rest/v1/orders?on_conflict=company,row_key"
    body = json.dumps(batch).encode("utf-8")
    last_err = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("apikey", SUPABASE_SERVICE_KEY)
        req.add_header("Authorization", f"Bearer {SUPABASE_SERVICE_KEY}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Prefer", "resolution=merge-duplicates,return=minimal")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp.read()
            return
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            last_err = RuntimeError(f"Supabase upsert failed ({e.code}): {detail}")
            if e.code < 500:
                raise last_err
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
        if attempt < attempts:
            time.sleep(2 * attempt)
    raise last_err


def refresh_views():
    url = f"{SUPABASE_URL}/rest/v1/rpc/refresh_dashboard_views"
    req = urllib.request.Request(url, data=b"{}", method="POST")
    req.add_header("apikey", SUPABASE_SERVICE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_SERVICE_KEY}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as resp:
        resp.read()


def main():
    total = 0
    failed = []
    for company, gid in GIDS.items():
        try:
            rows = build_rows(company, gid)
            for i in range(0, len(rows), BATCH_SIZE):
                upsert_batch(rows[i:i + BATCH_SIZE])
            total += len(rows)
            print(f"{company}: synced {len(rows)} rows", file=sys.stderr)
        except Exception as e:
            failed.append(company)
            print(f"{company}: FAILED - {e}", file=sys.stderr)
    print(f"done, total rows synced: {total}", file=sys.stderr)

    try:
        refresh_views()
        print("dashboard views refreshed", file=sys.stderr)
    except Exception as e:
        print(f"view refresh FAILED - {e}", file=sys.stderr)
        failed.append("refresh_dashboard_views")

    if failed:
        print(f"companies/steps with errors this run: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
