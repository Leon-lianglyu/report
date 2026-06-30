#!/usr/bin/env python3
"""Pull AEU & FRA data from Lark Base using App identity and write data.js."""
import json, os, sys
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from urllib.error import HTTPError

BASE_URL = "https://open.larksuite.com"
APP_TOKEN = "BFmTbNlNWaB2ursUGhilXBC7gJd"
TABLES = {
    "aeu": "tbl2xBDeojMd1SXP",
    "fra": "tblnOV7078lvNNxv",
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
    rows = []
    page_token = None
    headers = {"Authorization": f"Bearer {token}"}
    while True:
        params = {"page_size": 200}
        if page_token:
            params["page_token"] = page_token
        url = f"{BASE_URL}/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records?{urlencode(params)}"
        req = Request(url, headers=headers)
        with urlopen(req) as r:
            d = json.loads(r.read())
        if d.get("code") != 0:
            raise RuntimeError(f"API error {table_id}: {d}")
        items = d["data"]["items"]
        for item in items:
            rows.append(item["fields"])
        if not d["data"].get("has_more"):
            break
        page_token = d["data"].get("page_token")
        if not page_token:
            break
    return rows


def build_team(rows):
    members = {}
    month = None
    for r in rows:
        name = r.get("销售") or ""
        period = r.get("周期") or ""
        if not name:
            continue
        if month is None and r.get("月份"):
            month = r["月份"]
        if name not in members:
            members[name] = {}
        members[name][period] = r

    result = []
    for name, periods in members.items():
        m = periods.get("本月", {})
        w = periods.get("近7天", {})
        result.append({
            "name": name,
            "masterIB":     int(m.get("Master IB") or 0),
            "masterIBWeek": int(w.get("Master IB") or 0),
            "subIB":        int(m.get("Sub IB") or 0),
            "subIBWeek":    int(w.get("Sub IB") or 0),
            "cpa":          int(m.get("CPA") or 0),
            "cpaWeek":      int(w.get("CPA") or 0),
            "gross":        float(m.get("入金(USD)") or 0),
            "grossWeek":    float(w.get("入金(USD)") or 0),
            "net":          float(m.get("净入金(USD)") or 0),
            "netWeek":      float(w.get("净入金(USD)") or 0),
        })

    result.sort(key=lambda x: x["gross"], reverse=True)
    return result, month


def main():
    app_id = os.environ.get("LARK_APP_ID")
    app_secret = os.environ.get("LARK_APP_SECRET")
    if not app_id or not app_secret:
        sys.exit("Error: LARK_APP_ID and LARK_APP_SECRET env vars required")

    token = get_access_token(app_id, app_secret)

    teams = {}
    month = None
    for team, table_id in TABLES.items():
        rows = fetch_table(token, table_id)
        members, m = build_team(rows)
        teams[team] = members
        if m:
            month = m

    data = {
        "meta": {
            "month": month or datetime.now(timezone.utc).strftime("%Y-%m"),
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "aeu": teams["aeu"],
        "fra": teams["fra"],
    }

    with open("data.js", "w") as f:
        f.write("window.__DATA__ = ")
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    print(f"Written data.js  ({len(teams['aeu'])} AEU, {len(teams['fra'])} FRA members)")


if __name__ == "__main__":
    main()
