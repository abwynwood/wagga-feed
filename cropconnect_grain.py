import json
import re
from datetime import datetime, timezone
from pathlib import Path
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


def parse_odata_response(response):
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
    root = ET.fromstring(body)
    entries = []
    for entry in root.iter():
        if entry.tag.rsplit("}", 1)[-1] != "entry":
            continue
        entity = {}
        for child in entry.iter():
            if child.tag.rsplit("}", 1)[-1] == "properties":
                for prop in list(child):
                    entity[prop.tag.rsplit("}", 1)[-1]] = prop.text
        if entity:
            entries.append(entity)
    return entries


def odata_get(page, path, params):
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
    diagnostics = []
    bids = {}
    try:
        site_response, sites = odata_get(
            page,
            "SITE_PUBLIC/Site",
            {"$top": "2000", "$format": "json"},
        )
        diagnostics.append(f"Site API HTTP={site_response.status}, rows={len(sites)}")
        site_map = {}
        wanted = {loc.lower() for loc, _ in TARGETS}
        for item in sites:
            desc = normalise(item.get("SiteDescr") or item.get("SiteDescription") or item.get("SiteName") or item.get("Description") or "")
            if desc.lower() in wanted:
                site_no = item.get("SiteNo") or item.get("Site") or item.get("SiteID")
                if site_no:
                    site_map[desc.lower()] = str(site_no)
        diagnostics.append(f"Site map: {site_map}")

        code = season_code(season)
        for location, grade in TARGETS:
            site_no = site_map.get(location.lower())
            if not site_no:
                continue
            filt = (
                "(BidSustainable eq true) and (BidNonSustainable eq true) "
                f"and (SeasonYear eq '{code}') and (Grade eq '{grade}') and (SiteNo eq '{site_no}')"
            )
            response, results = odata_get(page, "BID_PUBLIC/AllBidsSet", {"$filter": filt, "$format": "json"})
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
            diagnostics.append(f"{location} {grade}: SiteNo={site_no}, rows={len(results)}, highest={max(prices) if prices else None}")
    except Exception as error:
        diagnostics.append(f"Direct OData unavailable: {error}")

    for line in diagnostics:
        print(f"CropConnect API: {line}")
    return bids


def matching_prices_in_object(obj, location, grade, season):
    """Find prices in a JSON object whose surrounding record identifies location, grade and season."""
    found = []
    loc_re = re.compile(rf"\b{re.escape(location)}\b", re.I)
    grade_re = re.compile(rf"\b{re.escape(grade)}\b", re.I)
    season_re = re.compile(rf"(?:\b{re.escape(season)}\b|\b{re.escape(season_code(season))}\b)")
    price_keys = {"price", "bidprice", "cashprice", "amount", "value"}
    season_keys = {"season", "seasonyear", "seasonyr", "seasonyrdesc", "cropseason", "marketingseason"}

    def walk(value):
        if isinstance(value, dict):
            text = normalise(" ".join(str(v) for v in value.values() if isinstance(v, (str, int, float))))
            if loc_re.search(text) and grade_re.search(text) and (season_re.search(text) or not any(str(k).lower() in season_keys for k in value)):
                for key, val in value.items():
                    if str(key).lower() in price_keys:
                        try:
                            p = float(val)
                            if 100 <= p <= 2000:
                                found.append(p)
                        except (TypeError, ValueError):
                            pass
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(obj)
    return found


def browser_data_bids(page, network_payloads, season):
    bids = {}
    targets = [(loc, grade, re.compile(rf"\b{re.escape(loc)}\b", re.I), re.compile(rf"\b{re.escape(grade)}\b", re.I)) for loc, grade in TARGETS]
    season_re = re.compile(rf"\b{re.escape(season)}\b")

    # First use rendered table rows. This is the same public data the user sees in CropConnect.
    for row in row_candidates(page):
        if not season_re.search(row):
            continue
        prices = prices_from_text(row)
        if not prices:
            continue
        for location, grade, loc_re, grade_re in targets:
            if loc_re.search(row) and grade_re.search(row):
                key = f"{location}|{grade}"
                bids[key] = max(bids.get(key, 0), max(prices))

    # Then inspect JSON returned by the site's own requests. This handles virtualized tables.
    for url, body in network_payloads:
        try:
            data = json.loads(body)
        except Exception:
            continue
        for location, grade, _, _ in targets:
            prices = matching_prices_in_object(data, location, grade, season)
            if prices:
                key = f"{location}|{grade}"
                bids[key] = max(bids.get(key, 0), max(prices))

    return bids


def fetch_all_bids():
    season = current_season()
    network_payloads = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1200})
        page = context.new_page()

        def capture_response(response):
            ctype = (response.headers.get("content-type") or "").lower()
            url = response.url
            # Keep API responses even when the server labels them unexpectedly.
            if "BID_PUBLIC" not in url and "SITE_PUBLIC" not in url and "json" not in ctype:
                return
            try:
                body = response.text()
                if body and len(body) < 5_000_000:
                    network_payloads.append((url, body))
            except Exception:
                pass

        page.on("response", capture_response)
        try:
            page.goto(CROPCONNECT_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(10000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(3000)

            bids = fetch_targeted_bids(page, season)
            browser_bids = browser_data_bids(page, network_payloads, season)
            for key, price in browser_bids.items():
                bids[key] = max(bids.get(key, 0), price)

            print(f"CropConnect snapshot: season={season}, matched={len(bids)}/{len(TARGETS)}, network_payloads={len(network_payloads)}")
            print(f"CropConnect matched bids: {bids}")
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
