import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
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
    # CropConnect grain seasons run October to September. On 10 Sep 2026,
    # for example, the current season is 25/26, not 26/27.
    now = datetime.now(ZoneInfo("Australia/Sydney"))
    start = now.year - 1 if now.month < 10 else now.year
    return f"{str(start)[-2:]}/{str(start + 1)[-2:]}"


def normalise(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def as_rows(payload):
    """Extract row lists from OData/JSON responses, including nested payloads."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("d", "value", "results"):
        value = payload.get(key)
        if isinstance(value, dict) and "results" in value:
            value = value["results"]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    rows = []
    for value in payload.values():
        rows.extend(as_rows(value))
    return rows


def get_json(url, params=None):
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    return requests.get(url, params=params, headers=headers, timeout=30)


def fetch_site_map():
    response = get_json(SITE_URL, {"$top": "1000", "$format": "json"})
    print(f"CropConnect API: Site API HTTP={response.status_code}")
    if response.status_code != 200:
        return {}
    rows = as_rows(response.json())
    site_map = {}
    for row in rows:
        site_no = row.get("SiteNo") or row.get("Site") or row.get("SiteID")
        text = " ".join(str(v) for v in row.values())
        for location in ("hillston", "condobolin"):
            if normalise(location) in normalise(text) and site_no is not None:
                site_map[location] = str(site_no)
    print(f"CropConnect API: Site rows={len(rows)}, site map={site_map}")
    return site_map


def fetch_all_bids():
    attempts = [
        (BID_URL, None),
        (BID_URL, {"$top": "5000"}),
        (BID_URL, {"$format": "json"}),
    ]
    for url, params in attempts:
        try:
            response = get_json(url, params)
            print(f"CropConnect API: AllBidsSet HTTP={response.status_code}, params={params}")
            if response.status_code == 200:
                rows = as_rows(response.json())
                print(f"CropConnect API: AllBidsSet rows={len(rows)}")
                if rows:
                    return rows
        except Exception as exc:
            print(f"CropConnect API: AllBidsSet error: {exc}")
    return []


def price_from_row(row):
    for key in ("Price", "BidPrice", "PricePerTonne", "PricePerTon"):
        value = row.get(key)
        if value is None:
            continue
        match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
        if match:
            return float(match.group(0))
    return None


def season_matches(value, season):
    raw = str(value or "").strip().lower()
    compact = re.sub(r"[^0-9]", "", raw)
    wanted = re.sub(r"[^0-9]", "", season)
    return raw == season.lower() or compact == wanted or compact == f"20{wanted[:2]}20{wanted[2:]}"


def grade_matches(value, grade):
    return normalise(value) == normalise(grade)


def site_matches(value, site_no):
    return site_no is not None and str(value or "").strip() == str(site_no).strip()


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
    payloads = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            def capture(response):
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type:
                    return
                try:
                    payloads.append(response.json())
                except Exception:
                    pass

            page.on("response", capture)
            page.goto(MARKET_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(15000)
            browser.close()
    except Exception as exc:
        print(f"CropConnect browser fallback failed: {exc}")
        return {}

    rows = []
    for payload in payloads:
        rows.extend(as_rows(payload))
    print(f"CropConnect browser fallback: JSON payloads={len(payloads)}, rows={len(rows)}")
    return find_bids(rows, site_map, season) if rows else {}


def write_xml(target, output, season, filename):
    # email.utils.format_datetime(usegmt=True) requires an actual UTC datetime.
    now = datetime.now(timezone.utc)
    pub_date = format_datetime(now, usegmt=True)
    slug = normalise(target)
    description = f"<strong>{target}</strong><br>{output}<br>Season {season}"
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{target}</title>
    <link>{MARKET_URL}</link>
    <language>en-au</language>
    <item>
      <title>{target}</title>
      <link>{MARKET_URL}</link>
      <guid>{slug}</guid>
      <pubDate>{pub_date}</pubDate>
      <description><![CDATA[
        {description}
      ]]></description>
    </item>
  </channel>
</rss>
'''
    Path(filename).write_text(xml, encoding="utf-8")
    print(f"Wrote {filename}: {output}")


def update(location, grade, filename):
    target = f"{location} {grade}"
    if target not in TARGETS:
        raise ValueError(f"Unsupported CropConnect target: {target}")

    season = current_season()
    site_map = fetch_site_map()
    rows = fetch_all_bids()
    matched = find_bids(rows, site_map, season) if rows else {}
    if target not in matched:
        fallback = browser_fallback(season, site_map)
        if target in fallback:
            matched[target] = fallback[target]

    value = matched.get(target)
    output = f"${value:.2f}/t" if value is not None else "Unavailable"
    print(f"CropConnect snapshot: season={season}, target={target}, output={output}")
    write_xml(target, output, season, filename)
    return output


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 4:
        raise SystemExit("Usage: python cropconnect_grain.py <location> <grade> <filename>")
    update(sys.argv[1], sys.argv[2], sys.argv[3])
