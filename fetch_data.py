#!/usr/bin/env python3
"""Pull AEU & FRA data from Lark Base and write data.js for index.html."""
import json, subprocess, sys
from datetime import datetime, timezone

BASE_TOKEN = "BFmTbNlNWaB2ursUGhilXBC7gJd"
TABLES = {
    "aeu": "tbl2xBDeojMd1SXP",
    "fra": "tblnOV7078lvNNxv",
}


def fetch_table(table_id):
    rows = []
    page_token = None
    while True:
        cmd = ["lark-cli", "base", "+record-list",
               "--base-token", BASE_TOKEN,
               "--table-id", table_id,
               "--as", "user",
               "--limit", "200",
               "--format", "json"]
        if page_token:
            cmd += ["--page-token", page_token]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        d = json.loads(result.stdout)
        if not d.get("ok"):
            raise RuntimeError(f"API error: {d}")
        payload = d["data"]
        fields = payload["fields"]
        for row in payload["data"]:
            rows.append(dict(zip(fields, row)))
        if not payload.get("has_more"):
            break
        page_token = payload.get("page_token")
        if not page_token:
            break
    return rows


def build_team(rows):
    """Group rows by 销售; each member has 本月 and 近7天 rows."""
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

    # sort by gross desc
    result.sort(key=lambda x: x["gross"], reverse=True)
    return result, month


def main():
    teams = {}
    month = None
    for team, table_id in TABLES.items():
        rows = fetch_table(table_id)
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

    out_path = "data.js"
    with open(out_path, "w") as f:
        f.write("window.__DATA__ = ")
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    print(f"Written {out_path}  ({len(teams['aeu'])} AEU, {len(teams['fra'])} FRA members)")


if __name__ == "__main__":
    main()
