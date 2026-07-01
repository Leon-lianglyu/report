#!/usr/bin/env python3
"""Pull daily records from Lark Base, aggregate by month, and write data.js."""
import json, os, sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.parse import urlencode

BASE_URL = "https://open.larksuite.com"
APP_TOKEN = "BFmTbNlNWaB2ursUGhilXBC7gJd"
TABLES = {
    "aeu": "tbl2xBDeojMd1SXP",
    "fra": "tblnOV7078lvNNxv",
    "cr":  "tblph7EE0LZDcgrC",
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
    """Safe numeric cast."""
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def aggregate_team(rows, date_field, month_field):
    """
    Aggregate daily rows by month and compute last-7-days totals.
    Returns: (by_month, last7)
      by_month: {"2026-06": {"MemberName": {masterIB, subIB, cpa, gross, net}}}
      last7:    {"MemberName": {masterIBWeek, subIBWeek, cpaWeek, grossWeek, netWeek}}
    """
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=7)

    by_month = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    last7 = defaultdict(lambda: defaultdict(float))

    for r in rows:
        name = r.get("销售") or ""
        if not name:
            continue
        month = r.get(month_field) or ""
        date_str = r.get(date_field) or ""

        # parse date (format: "YYYY-MM-DD")
        date_val = None
        if date_str and len(date_str) >= 10:
            try:
                date_val = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
            except ValueError:
                pass

        if month:
            m = by_month[month][name]
            m["masterIB"] += _n(r.get("Master IB"))
            m["subIB"]    += _n(r.get("Sub IB"))
            m["cpa"]      += _n(r.get("CPA"))
            m["gross"]    += _n(r.get("入金(USD)"))
            m["net"]      += _n(r.get("净入金(USD)"))

        if date_val and date_val > cutoff:
            w = last7[name]
            w["masterIBWeek"] += _n(r.get("Master IB"))
            w["subIBWeek"]    += _n(r.get("Sub IB"))
            w["cpaWeek"]      += _n(r.get("CPA"))
            w["grossWeek"]    += _n(r.get("入金(USD)"))
            w["netWeek"]      += _n(r.get("净入金(USD)"))

    return by_month, last7


def build_month_members(member_map, last7_map, include_week=True):
    """Convert member dicts to sorted list, merging weekly deltas."""
    result = []
    all_names = set(member_map.keys()) | set(last7_map.keys())
    for name in all_names:
        m = member_map.get(name, {})
        w = last7_map.get(name, {})
        entry = {
            "name":     name,
            "masterIB": int(round(m.get("masterIB", 0))),
            "subIB":    int(round(m.get("subIB", 0))),
            "cpa":      int(round(m.get("cpa", 0))),
            "gross":    round(m.get("gross", 0), 2),
            "net":      round(m.get("net", 0), 2),
        }
        if include_week:
            entry["masterIBWeek"] = int(round(w.get("masterIBWeek", 0)))
            entry["subIBWeek"]    = int(round(w.get("subIBWeek", 0)))
            entry["cpaWeek"]      = int(round(w.get("cpaWeek", 0)))
            entry["grossWeek"]    = round(w.get("grossWeek", 0), 2)
            entry["netWeek"]      = round(w.get("netWeek", 0), 2)
        result.append(entry)
    result.sort(key=lambda x: x["gross"], reverse=True)
    return result


def main():
    app_id     = os.environ.get("LARK_APP_ID")
    app_secret = os.environ.get("LARK_APP_SECRET")
    if not app_id or not app_secret:
        sys.exit("Error: LARK_APP_ID and LARK_APP_SECRET env vars required")

    token = get_access_token(app_id, app_secret)

    # Fetch and aggregate each team
    aeu_rows = fetch_table(token, TABLES["aeu"])
    fra_rows = fetch_table(token, TABLES["fra"])
    cr_rows  = fetch_table(token, TABLES["cr"])

    aeu_by_month, aeu_last7 = aggregate_team(aeu_rows, "周期", "月份")
    fra_by_month, fra_last7 = aggregate_team(fra_rows, "周期", "月份")
    cr_by_month,  _         = aggregate_team(cr_rows,  "日期", "月")

    # Collect all months across all teams
    all_months = sorted(
        set(aeu_by_month) | set(fra_by_month) | set(cr_by_month),
        reverse=True
    )

    months_data = {}
    for month in all_months:
        months_data[month] = {
            "aeu": build_month_members(aeu_by_month.get(month, {}), aeu_last7, include_week=True),
            "fra": build_month_members(fra_by_month.get(month, {}), fra_last7, include_week=True),
            "cr":  build_month_members(cr_by_month.get(month, {}),  {},         include_week=False),
        }

    current_month = all_months[0] if all_months else datetime.now(timezone.utc).strftime("%Y-%m")

    data = {
        "meta": {
            "currentMonth": current_month,
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "months": months_data,
    }

    with open("data.js", "w") as f:
        f.write("window.__DATA__ = ")
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    print(f"Written data.js  months={all_months}  "
          f"AEU={len(aeu_last7)} FRA={len(fra_last7)} CR members")


if __name__ == "__main__":
    main()
