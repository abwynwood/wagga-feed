import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright

BASE = "https://cropconnect.com.au"
SITE_URL = f"{BASE}/sap/opu/odata/SAP/SITE_PUBLIC/Site"
BID_URL = f"{BASE}/sap/opu/odata/SAP/BID_PUBLIC/AllBidsSet"
MARKET_URL = f"{BASE}/cc/market/bids"

TARGETS = {
    "Hillston APW1": ("Hillston", "APW1"),
    "Hillston BAR1": ("Hillston", "BAR1"),
    "Condobolin APW1": ("Condobolin", "APW1"),
    "Condobolin BAR1": ("Condobolin", "BAR1"),
}


def current_season():
    now = datetime.now(ZoneInfo("Australia/Sydney"))
    start = now.year if now.month >= 7 else now.year - 1
    return f"{str(start)[-2:]}/{str(start + 1)[-2:]}"


def normalise(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def as_rows(payload):
    if isinstance(payload, dict):
        for key in ("d", "value", "results"):
            value = payload.get(key)
            if isinstance(value, dict) and "results" in value:
                value = value["results"]
            if isinstance(value, list):
                return value
    return []


def get_json(url, params=None):
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    response = requests.get(url, params=params, headers=headers, timeout=30)
    return response


def fetch_site_map():
    response = get_json(SITE_URL, {"$top": "1000", "$format": "json"})
    if response.status_code != 200:
        print(f"CropConnect API: Site API HTTP={response.status_code}")
        return {}

    rows = as_rows(response.json())
    site_map = {}
    for row in rows:
        site_no = row.get("SiteNo") or row.get("Site") or row.get("SiteID")
        text = " ".join(str(v) for v in row.values())
        for location in ("hillston", "condobolin"):
            if normalise(location) in normalise(text) and site_no is not None:
                site_map[location] = str(site_no)

    print(f"CropConnect API: Site API HTTP=200, rows={len(rows)}")
    print(f"CropConnect API: Site map: {site_map}")
    return site_map


def fetch_all_bids():
    # The public endpoint rejects the compound OData filters, so request the
    # public collection and filter locally using SiteNo, Grade and SeasonYear.
    response = get_json(BID_URL, {"$top": "5000", "$format": "json"})
    print(f"CropConnect API: AllBidsSet HTTP={response.status_code}")
    if response.status_code != 200:
        return []

    rows = as_rows(response.json())
    print(f"CropConnect API: AllBidsSet rows={len(rows)}")
    return rows


def price_from_row(row):
    for key in ("Price", "BidPrice", "PricePerTonne", "PricePerTon"):
        value = row.get(key)
        if value is None:
            continue
        match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                pass
    return None


def season_matches(value, season):
    raw = str(value or "").strip().lower()
    compact = re.sub(r"[^0-9]", "", raw)
    wanted = re.sub(r"[^0-9]", "", season)
    return raw == season.lower() or compact == wanted or compact == wanted[:2]


def grade_matches(value, grade):
    return normalise(value) == normalise(grade)


def site_matches(value, site_no):
    if site_no is None:
        return False
    return str(value or "").strip() == str(site_no).strip()


def find_bids(rows, site_map, season):
    matched = {}
    for name, (location, grade) in TARGETS.items():
        site_no = site_map.get(normalise(location))
        prices = []
        for row in rows:
            if not site_matches(row.get("SiteNo") or row.get("Site") or row.get("SiteID"), site_no):
                continue
            if not grade_matches(row.get("Grade"), grade):
                continue
            if not season_matches(row.get("SeasonYear") or row.get("Season") or row.get("SeasonYr"), season):
                continue
            price = price_from_row(row)
            if price is not None:
                prices.append(price)

        if prices:
            matched[name] = max(prices)
        print(f"CropConnect target: {name}, site={site_no}, bids={len(prices)}, highest={matched.get(name)}")

    return matched


def browser_fallback(season, site_map):
    # Keep the rendered/network fallback for cases where the public OData
    # collection is temporarily unavailable.
    payloads = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            def capture(response):
                content_type = response.headers.get("content-type", "")
                if "json" in content_type:
                    try:
                        payloads.append(response.json())
                    except Exception:
                        pass

            page.on("response", capture)
            page.goto(MARKET_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(10000)
            browser.close()
    except Exception as exc:
        print(f"CropConnect browser fallback failed: {exc}")
        return {}

    all_rows = []
    for payload in payloads:
        all_rows.extend(as_rows(payload))

    return find_bids(all_rows, site_map, season)


def update(target):
    season = current_season()
    site_map = fetch_site_map()
    rows = fetch_all_bids()
    matched = find_bids(rows, site_map, season) if rows else {}

    if not matched:
        fallback = browser_fallback(season, site_map)
        if fallback:
            matched = fallback

    print(f"CropConnect snapshot: season={season}, matched={len(matched)}/4")
    print(f"CropConnect matched bids: {matched}")

    value = matched.get(target)
    output = f"${value:.2f}/t" if value is not None else "Unavailable"
    print(f"{target}: {output}")
    return output


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2 or sys.argv[1] not in TARGETS:
        raise SystemExit(f"Usage: python cropconnect_grain.py [{', '.join(TARGETS)}]")
    update(sys.argv[1])
