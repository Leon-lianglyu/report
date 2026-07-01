#!/usr/bin/env python3
"""Pull daily records from Lark Base and write raw data.js for client-side aggregation."""
import json, os, sys
from collections import defaultdict
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.parse import urlencode

BASE_URL = "https://open.larksuite.com"
APP_TOKEN = "BFmTbNlNWaB2ursUGhilXBC7gJd"
TABLES = {
    "aeu": ("tbl2xBDeojMd1SXP", "周期", "月份"),
    "fra": ("tblnOV7078lvNNxv", "周期", "月份"),
    "cr":  ("tblph7EE0LZDcgrC", "日期", "月"),
}


def get_access_token(app_id, app_secret):
    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = Request(f"{BASE_URL}/open-apis/auth/v3/tenant_access_token/internal",
                  data=body, headers={"Content-Type": "application/json"})
    with urlopen(req) as r:
        d = json.loads(r.read())
    if d.get("code") != 0:
        raise RuntimeError(f"Auth failed: {d}")
    return d["tenant_access_token"]


def fetch_table(token, table_id):
    rows, page_token = [], None
    headers = {"Authorization": f"Bearer {token}"}
    while True:
        params = {"page_size": 200}
        if page_token:
            params["page_token"] = page_token
        url = f"{BASE_URL}/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records?{urlencode(params)}"
        with urlopen(Request(url, headers=headers)) as r:
            d = json.loads(r.read())
        if d.get("code") != 0:
            raise RuntimeError(f"API error {table_id}: {d}")
        for item in d["data"]["items"]:
            rows.append(item["fields"])
        if not d["data"].get("has_more"):
            break
        page_token = d["data"].get("page_token")
        if not page_token:
            break
    return rows


def _n(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def extract_records(rows, date_field, month_field, is_cr=False):
    """Convert raw rows to {month: [daily records]} structure."""
    by_month = defaultdict(list)
    for r in rows:
        name = r.get("销售") or ""
        month = r.get(month_field) or ""
        date = r.get(date_field) or ""
        if not name or not month or not date:
            continue
        date = date[:10]  # trim to YYYY-MM-DD
        rec = {
            "name":     name,
            "date":     date,
            "masterIB": int(_n(r.get("Master IB"))),
            "subIB":    int(_n(r.get("Sub IB"))),
            "gross":    round(_n(r.get("入金(USD)")), 2),
            "net":      round(_n(r.get("净入金(USD)")), 2),
        }
        if not is_cr:
            rec["cpa"] = int(_n(r.get("CPA")))
        by_month[month].append(rec)
    return by_month


def main():
    app_id     = os.environ.get("LARK_APP_ID")
    app_secret = os.environ.get("LARK_APP_SECRET")
    if not app_id or not app_secret:
        sys.exit("Error: LARK_APP_ID and LARK_APP_SECRET env vars required")

    token = get_access_token(app_id, app_secret)

    all_by_month = {}
    all_months = set()

    for team, (table_id, date_field, month_field) in TABLES.items():
        rows = fetch_table(token, table_id)
        by_month = extract_records(rows, date_field, month_field, is_cr=(team == "cr"))
        all_months |= set(by_month.keys())
        for month, records in by_month.items():
            all_by_month.setdefault(month, {})[team] = records

    sorted_months = sorted(all_months, reverse=True)
    current_month = sorted_months[0] if sorted_months else datetime.now(timezone.utc).strftime("%Y-%m")

    # Ensure all teams present in every month
    months_data = {}
    for month in sorted_months:
        md = all_by_month.get(month, {})
        months_data[month] = {
            "aeu": md.get("aeu", []),
            "fra": md.get("fra", []),
            "cr":  md.get("cr", []),
        }

    data = {
        "meta": {
            "currentMonth": current_month,
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "months": months_data,
    }

    with open("data.js", "w") as f:
        f.write("window.__DATA__ = ")
        json.dump(data, f, ensure_ascii=False)
        f.write(";\n")

    counts = {team: sum(len(months_data[m].get(team,[])) for m in sorted_months) for team in ["aeu","fra","cr"]}
    print(f"Written data.js  months={sorted_months}  records={counts}")


if __name__ == "__main__":
    main()
