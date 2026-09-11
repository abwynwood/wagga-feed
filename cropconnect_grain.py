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
    "Lake Cargelligo BAR1": ("Lake Cargelligo", "BAR1"),
    "Condobolin APW1": ("Condobolin", "APW1"),
    "Condobolin BAR1": ("Condobolin", "BAR1"),
}


def current_season():
    now = datetime.now(ZoneInfo("Australia/Sydney"))
    start = now.year - 1 if now.month < 10 else now.year
    return f"{str(start)[-2:]}/{str(start + 1)[-2:]}"


def normalise(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def as_rows(payload):
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
        for location in ("hillston", "lake cargelligo", "condobolin"):
            if normalise(location) in normalise(text) and site_no is not None:
                site_map[normalise(location)] = str(site_no)
    print(f"CropConnect API: Site rows={len(rows)}, site map={site_map}")
    return site_map


def fetch_all_bids():
    """Fetch the same public bid collection the CropConnect web app uses, page by page."""
    rows = []
    skip = 0
    page_size = 500
    total = None
    params_base = {
        "$filter": "(BidSustainable eq true) and (BidNonSustainable eq true)",
        "$orderby": "Price desc, BidTypeDesc asc",
        "$top": str(page_size),
        "$inlinecount": "allpages",
    }

    while True:
        params = dict(params_base)
        params["$skip"] = str(skip)
        try:
            response = get_json(BID_URL, params)
            print(f"CropConnect API: AllBidsSet page skip={skip} HTTP={response.status_code}")
            if response.status_code != 200:
                print(f"CropConnect API: AllBidsSet error body={response.text[:500]}")
                break
            payload = response.json()
            page_rows = as_rows(payload)
            rows.extend(page_rows)
            if skip == 0 and page_rows:
                print(f"CropConnect API: AllBidsSet bid keys={sorted(page_rows[0].keys())}")
                print(f"CropConnect API: AllBidsSet sample={page_rows[0]}")
            if isinstance(payload, dict):
                data = payload.get("d")
                if isinstance(data, dict) and data.get("__count") is not None:
                    try:
                        total = int(data["__count"])
                    except (TypeError, ValueError):
                        pass
                if payload.get("@odata.count") is not None:
                    try:
                        total = int(payload["@odata.count"])
                    except (TypeError, ValueError):
                        pass
            print(f"CropConnect API: AllBidsSet page rows={len(page_rows)}, collected={len(rows)}, total={total}")
            if not page_rows or len(page_rows) < page_size:
                break
            if total is not None and len(rows) >= total:
                break
            skip += page_size
        except Exception as exc:
            print(f"CropConnect API: AllBidsSet error: {exc}")
            break

    print(f"CropConnect API: AllBidsSet total rows collected={len(rows)}")
    return rows


def row_value(row, aliases):
    wanted = {normalise(alias) for alias in aliases}
    for key, value in row.items():
        if normalise(key) in wanted:
            return value
    return None


def values_for_key_tokens(row, tokens):
    tokens = tuple(normalise(token) for token in tokens)
    values = []
    for key, value in row.items():
        key_norm = normalise(key)
        if any(token in key_norm for token in tokens):
            values.append(value)
    return values


def row_values_text(row):
    return " ".join(str(v) for v in row.values())


def price_from_row(row):
    value = row_value(row, ("Price", "BidPrice", "PricePerTonne", "PricePerTon"))
    if value is None:
        for candidate in values_for_key_tokens(row, ("price",)):
            if candidate is not None:
                value = candidate
                break
    if value is None:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def season_matches(value, season):
    raw = str(value or "").strip().lower()
    compact = re.sub(r"[^0-9]", "", raw)
    wanted = re.sub(r"[^0-9]", "", season)
    return raw == season.lower() or compact == wanted or compact == f"20{wanted[:2]}20{wanted[2:]}"


def grade_matches(value, grade):
    return normalise(value) == normalise(grade)


def location_or_site_matches(row, location, site_no):
    explicit = row_value(row, ("SiteNo", "Site", "SiteID", "SiteNumber", "Location", "SiteName", "SiteDescr", "SiteDescription"))
    if explicit is not None:
        value = normalise(explicit)
        if value == normalise(site_no) or value == normalise(location):
            return True
    for value in values_for_key_tokens(row, ("site", "location")):
        value_norm = normalise(value)
        if value_norm == normalise(site_no) or value_norm == normalise(location):
            return True
    return False


def find_bids(rows, site_map, season):
    matched = {}
    for name, (location, grade) in TARGETS.items():
        site_no = site_map.get(normalise(location))
        prices = []
        for row in rows:
            if not location_or_site_matches(row, location, site_no):
                continue

            grade_value = row_value(row, ("Grade", "GradeCode", "CommodityGrade", "ProductGrade", "GradeDesc", "GradeDescription"))
            grade_candidates = [grade_value] if grade_value is not None else []
            grade_candidates.extend(values_for_key_tokens(row, ("grade",)))
            if not any(grade_matches(value, grade) for value in grade_candidates):
                continue

            season_value = row_value(row, ("SeasonYear", "Season", "SeasonYr", "SeasonCode", "CropYear", "SeasonDesc", "SeasonDescription"))
            season_candidates = [season_value] if season_value is not None else []
            season_candidates.extend(values_for_key_tokens(row, ("season", "cropyear")))
            if not any(season_matches(value, season) for value in season_candidates):
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
    json_urls = []
    all_urls = []
    page_text = ""
    frame_urls = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            def capture(response):
                url = response.url
                if "cropconnect.com.au" in url and url not in all_urls:
                    all_urls.append(url)
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type:
                    return
                if url not in json_urls:
                    json_urls.append(url)
                try:
                    payloads.append(response.json())
                except Exception:
                    pass

            page.on("response", capture)
            page.goto(MARKET_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(15000)
            frame_urls = [frame.url for frame in page.frames]
            try:
                page_text = page.locator("body").inner_text(timeout=5000)
            except Exception:
                pass
            browser.close()
    except Exception as exc:
        print(f"CropConnect browser fallback failed: {exc}")
        return {}

    print(f"CropConnect browser fallback: JSON payloads={len(payloads)}, rows={sum(len(as_rows(p)) for p in payloads)}")
    print(f"CropConnect browser network: json_urls={json_urls[:30]}")
    print(f"CropConnect browser network: frame_urls={frame_urls[:20]}")
    if all_urls:
        interesting = [u for u in all_urls if any(x in u.lower() for x in ("bid", "market", "odata", "api"))]
        print(f"CropConnect browser network: interesting_urls={interesting[:50]}")
    if page_text:
        compact_text = re.sub(r"\s+", " ", page_text).strip()
        print(f"CropConnect browser text sample: {compact_text[:3000]}")

    rows = []
    for payload in payloads:
        rows.extend(as_rows(payload))
    if rows:
        print(f"CropConnect browser sample keys: {sorted(rows[0].keys())}")
        for location in ("Hillston", "Condobolin", "Lake Cargelligo"):
            candidates = [r for r in rows if normalise(location) in normalise(row_values_text(r))]
            print(f"CropConnect browser diagnostic: {location} text-matches={len(candidates)}")
            for row in candidates[:3]:
                print(f"CropConnect browser candidate {location}: {row}")
    return find_bids(rows, site_map, season) if rows else {}


def write_xml(target, output, season, filename):
    now = datetime.now(timezone.utc)
    pub_date = format_datetime(now, usegmt=True)
    slug = normalise(target)
    description = f"{output}<br>Season {season}"
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
