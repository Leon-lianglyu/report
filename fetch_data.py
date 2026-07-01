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
    "aeu": ("tbl2xBDeojMd1SXP", "日期", "月份"),
    "fra": ("tblnOV7078lvNNxv", "日期", "月份"),
    "cr":  ("tblph7EE0LZDcgrC", "日期", "月份"),
    "x5":  ("tblwtWY7l6MVyucg", "日期", "月份"),
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


def _str(v):
    """Normalize a Lark field value (str / list / dict / number) to a plain string."""
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        v = v[0] if v else ""
    if isinstance(v, dict):
        # try common text-field keys; if none found return ""
        for key in ("text", "value", "en_us"):
            candidate = v.get(key)
            if candidate and isinstance(candidate, str):
                return candidate
        return ""
    return str(v) if v else ""


def extract_records(rows, date_field, month_field, is_cr=False, has_supervisor=False):
    """Convert raw rows to {month: [daily records]} structure."""
    by_month = defaultdict(list)
    for r in rows:
        name  = _str(r.get("销售"))
        month = _str(r.get(month_field))
        date  = _str(r.get(date_field))
        if not name or not month or not date:
            continue
        date  = date[:10]
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
        if has_supervisor:
            rec["supervisor"] = _str(r.get("supervisor"))
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
        if rows:
            r0 = rows[0]
            print(f"{team}: {len(rows)} rows | {month_field}={r0.get(month_field)!r} | {date_field}={r0.get(date_field)!r}")
        by_month = extract_records(rows, date_field, month_field,
                                   is_cr=(team == "cr"),
                                   has_supervisor=(team == "x5"))
        all_months |= set(by_month.keys())
        for month, records in by_month.items():
            all_by_month.setdefault(month, {})[team] = records

    sorted_months = sorted(all_months, reverse=True)
    current_month = sorted_months[0] if sorted_months else datetime.now(timezone.utc).strftime("%Y-%m")

    months_data = {}
    for month in sorted_months:
        md = all_by_month.get(month, {})
        months_data[month] = {
            "aeu": md.get("aeu", []),
            "fra": md.get("fra", []),
            "cr":  md.get("cr", []),
            "x5":  md.get("x5", []),
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

    counts = {t: sum(len(months_data[m].get(t,[])) for m in sorted_months) for t in ["aeu","fra","cr","x5"]}
    print(f"Written data.js  months={sorted_months}  records={counts}")


if __name__ == "__main__":
    main()
