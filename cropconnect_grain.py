import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

from playwright.sync_api import sync_playwright

CROPCONNECT_URL = "https://cropconnect.com.au/cc/market/bids"
API_BASE = "https://cropconnect.com.au/sap/opu/odata/SAP"
CACHE_FILE = Path("/tmp/cropconnect_bids.json")
TARGETS = [
    ("Hillston", "APW1"),
    ("Hillston", "BAR1"),
    ("Condobolin", "APW1"),
    ("Condobolin", "BAR1"),
]


def current_season():
    now = datetime.now(ZoneInfo("Australia/Sydney"))
    if now.month >= 10:
        start = now.year
        end = now.year + 1
    else:
        start = now.year - 1
        end = now.year
    return f"{start % 100:02d}/{end % 100:02d}"


def season_code(season):
    return season.split("/")[0]


def normalise(text):
    return re.sub(r"\s+", " ", text or "").strip()


def prices_from_text(text):
    return [float(x.replace(",", "")) for x in re.findall(r"\$\s*([0-9][0-9,]*(?:\.\d+)?)", text)]


def row_candidates(page):
    rows = []
    selectors = ["tr", '[role="row"]', ".ag-row", ".MuiDataGrid-row"]
    for frame in page.frames:
        for selector in selectors:
            try:
                for text in frame.locator(selector).all_inner_texts():
                    text = normalise(text)
                    if text:
                        rows.append(text)
            except Exception:
                pass
    return rows


def all_frame_text(page):
    texts = []
    for frame in page.frames:
        try:
            text = normalise(frame.locator("body").inner_text(timeout=5000))
            if text:
                texts.append(text)
        except Exception:
            pass
    return texts


def parse_odata_response(response):
    """Return OData entities from JSON or Atom/XML responses."""
    content_type = (response.headers.get("content-type") or "").lower()
    body = response.text()
    if not body:
        return []

    if "json" in content_type or body.lstrip().startswith(("{", "[")):
        data = json.loads(body)
        if isinstance(data, dict):
            d = data.get("d", data)
            if isinstance(d, dict):
                return d.get("results", [])
            if isinstance(d, list):
                return d
        return data if isinstance(data, list) else []

    # SAP OData commonly defaults to Atom/XML when JSON is not explicitly requested.
    root = ET.fromstring(body)
    entries = []
    for entry in root.iter():
        if entry.tag.rsplit("}", 1)[-1] != "entry":
            continue
        entity = {}
        for child in entry.iter():
            if child.tag.rsplit("}", 1)[-1] != "properties":
                continue
            for prop in list(child):
                name = prop.tag.rsplit("}", 1)[-1]
                entity[name] = prop.text
        if entity:
            entries.append(entity)
    return entries


def odata_get(page, path, params):
    """Request OData with explicit JSON preference and XML fallback support."""
    response = page.request.get(
        f"{API_BASE}/{path}",
        params=params,
        headers={
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": CROPCONNECT_URL,
        },
        timeout=60000,
    )
    if not response.ok:
        raise RuntimeError(f"{path} returned HTTP {response.status}")
    return response, parse_odata_response(response)


def fetch_targeted_bids(page, season):
    """Use CropConnect's public OData API directly for the four exact targets."""
    diagnostics = []
    site_response, sites = odata_get(
        page,
        "SITE_PUBLIC/Site",
        {"$top": "2000", "$format": "json"},
    )
    diagnostics.append(
        f"Site API HTTP={site_response.status}, type={site_response.headers.get('content-type', '')}, rows={len(sites)}"
    )

    site_map = {}
    wanted = {loc.lower() for loc, _ in TARGETS}
    for item in sites:
        desc = normalise(
            item.get("SiteDescr")
            or item.get("SiteDescription")
            or item.get("SiteName")
            or item.get("Description")
            or ""
        )
        if desc.lower() in wanted:
            site_no = item.get("SiteNo") or item.get("Site") or item.get("SiteID")
            if site_no:
                site_map[desc.lower()] = str(site_no)

    diagnostics.append(f"Site map: {site_map}")
    bids = {}
    code = season_code(season)

    for location, grade in TARGETS:
        site_no = site_map.get(location.lower())
        if not site_no:
            diagnostics.append(f"{location} {grade}: no matching site")
            continue

        filt = (
            "(BidSustainable eq true) and (BidNonSustainable eq true) "
            f"and (SeasonYear eq '{code}') and (Grade eq '{grade}') and (SiteNo eq '{site_no}')"
        )
        response, results = odata_get(
            page,
            "BID_PUBLIC/AllBidsSet",
            {"$filter": filt, "$format": "json"},
        )
        diagnostics.append(
            f"{location} {grade}: SiteNo={site_no}, HTTP={response.status}, type={response.headers.get('content-type', '')}, rows={len(results)}"
        )

        prices = []
        for item in results:
            try:
                price = float(item.get("Price"))
                if 100 <= price <= 2000:
                    prices.append(price)
            except (TypeError, ValueError):
                pass

        if prices:
            bids[f"{location}|{grade}"] = max(prices)
            diagnostics.append(f"{location} {grade}: highest={max(prices)}")
        else:
            diagnostics.append(f"{location} {grade}: bids=0")

    for line in diagnostics:
        print(f"CropConnect API: {line}")
    return bids


def price_from_matching_json(value, location, grade, season):
    found = []
    location_re = re.compile(rf"\b{re.escape(location)}\b", re.I)
    grade_re = re.compile(rf"\b{re.escape(grade)}\b", re.I)
    season_re = re.compile(rf"\b{re.escape(season)}\b")
    price_keys = {"price", "bidprice", "cashprice", "amount", "value"}
    season_keys = {"season", "seasonyr", "seasonyrdesc", "cropseason", "marketingseason"}

    def walk(obj):
        if isinstance(obj, dict):
            blob = normalise(json.dumps(obj, ensure_ascii=False))
            if location_re.search(blob) and grade_re.search(blob):
                seasons = [str(val) for key, val in obj.items() if str(key).lower() in season_keys]
                if not seasons or any(season_re.search(s) or season_code(season) in s for s in seasons):
                    for key, val in obj.items():
                        if str(key).lower() in price_keys and isinstance(val, (int, float)):
                            if 100 <= float(val) <= 2000:
                                found.append(float(val))
            for child in obj.values():
                walk(child)
        elif isinstance(obj, list):
            for child in obj:
                walk(child)

    walk(value)
    return found


def fetch_all_bids():
    season = current_season()
    if CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if cached.get("season") == season:
                return cached.get("bids", {}), season
        except Exception:
            pass

    network_json = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1200})
        page = context.new_page()

        def capture_response(response):
            ctype = (response.headers.get("content-type") or "").lower()
            if "json" not in ctype:
                return
            try:
                body = response.text()
                if body and len(body) < 2_000_000:
                    network_json.append((response.url, body))
            except Exception:
                pass

        page.on("response", capture_response)
        try:
            page.goto(CROPCONNECT_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(8000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(2000)

            bids = fetch_targeted_bids(page, season)

            if len(bids) < len(TARGETS):
                season_re = re.compile(rf"\b{re.escape(season)}\b")
                location_grade = [(loc, grd, re.compile(rf"\b{re.escape(loc)}\b", re.I), re.compile(rf"\b{re.escape(grd)}\b", re.I)) for loc, grd in TARGETS]
                for row in row_candidates(page):
                    if not season_re.search(row):
                        continue
                    prices = prices_from_text(row)
                    if not prices:
                        continue
                    for location, grade, location_re, grade_re in location_grade:
                        if location_re.search(row) and grade_re.search(row):
                            key = f"{location}|{grade}"
                            bids[key] = max(bids.get(key, 0), max(prices))

                for url, body in network_json:
                    try:
                        data = json.loads(body)
                    except Exception:
                        continue
                    for location, grade, _, _ in location_grade:
                        prices = price_from_matching_json(data, location, grade, season)
                        if prices:
                            key = f"{location}|{grade}"
                            bids[key] = max(bids.get(key, 0), max(prices))

            CACHE_FILE.write_text(json.dumps({"season": season, "bids": bids}), encoding="utf-8")
            print(f"CropConnect snapshot: season={season}, matched={len(bids)}/{len(TARGETS)}, json_responses={len(network_json)}")
            return bids, season
        finally:
            context.close()
            browser.close()


def fetch_highest_bid(location, grade):
    bids, season = fetch_all_bids()
    return bids.get(f"{location}|{grade}"), season


def write_xml(location, grade, output_file, price, season):
    now = datetime.now(timezone.utc)
    value = f"${price:,.0f}/t" if price is not None else "Unavailable"
    Path(output_file).write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{location} {grade}</title>
    <link>{CROPCONNECT_URL}</link>
    <language>en-au</language>
    <item>
      <title>{location} {grade}</title>
      <link>{CROPCONNECT_URL}</link>
      <guid>{location.lower().replace(" ", "-")}-{grade.lower()}</guid>
      <pubDate>{now.strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
      <description><![CDATA[
        <strong>{location} {grade}</strong><br>
        {value}<br>
        Season {season}
      ]]></description>
    </item>
  </channel>
</rss>
''',
        encoding="utf-8",
    )


def update(location, grade, output_file):
    try:
        price, season = fetch_highest_bid(location, grade)
    except Exception as error:
        print(f"CropConnect fetch failed for {location} {grade}: {error}")
        price = None
        season = current_season()

    write_xml(location, grade, output_file, price, season)
    if price is None:
        print(f"{location} {grade}: Unavailable")
    else:
        print(f"{location} {grade}: ${price:,.0f}/t (highest CropConnect bid, season {season})")


if __name__ == "__main__":
    raise SystemExit("Import cropconnect_grain.update() from the individual feed scripts.")
