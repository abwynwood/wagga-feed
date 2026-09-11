import re
from datetime import datetime, timezone
from pathlib import Path

import requests

API_BASE = "https://api-mlastatistics.mla.com.au"
MLA_STATISTICS_URL = "https://www.mla.com.au/prices-markets/statistics/"
OUTPUT_FILE = Path(__file__).with_name("goats.xml")
HEADERS = {"User-Agent": "wagga-feed/1.0", "Accept": "application/json"}


def get_json(path, params=None):
    response = requests.get(API_BASE + path, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def walk_objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_objects(child)


def text_of(obj):
    return " ".join(str(v) for v in obj.values() if isinstance(v, (str, int, float)))


def number_from_obj(obj):
    preferred = ("average", "avg", "averageprice", "avgprice", "price", "value", "indicatorvalue", "indicator_value", "avgvalue", "avg_value")
    for wanted in preferred:
        for key, value in obj.items():
            if str(key).lower() == wanted:
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, str):
                    match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
                    if match:
                        return float(match.group(0))
    return None


def date_key(obj):
    for key, value in obj.items():
        if any(term in str(key).lower() for term in ("date", "period", "week")) and isinstance(value, str):
            match = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", value)
            if match:
                return match.group(0)
    return ""


def is_goat_row(obj):
    text = text_of(obj).lower()
    return "goat" in text and ("over the hooks" in text or "over-the-hooks" in text or "oth" in text or "16-20" in text.replace(" ", "") or "16–20" in text or "16 to 20" in text)


def is_16_20_row(obj):
    text = text_of(obj).lower()
    compact = text.replace(" ", "")
    return (("16" in compact and "20" in compact and ("kg" in compact or "cwt" in compact)) or "16-20" in compact or "16–20" in text or "16 to 20" in text)


def fetch_goat_price():
    # MLA's published NSW benchmark is the Eastern States goat OTH indicator.
    # Use the 16–20kg cwt category used in NSW DPIRD reporting.
    attempts = [
        {"page": 1, "pageSize": 200},
        {"page": 1, "page_size": 200},
        None,
    ]
    all_candidates = []
    for params in attempts:
        try:
            data = get_json("/report/5", params=params)
        except requests.RequestException as error:
            print(f"MLA report request failed for {params}: {error}")
            continue
        rows = [obj for obj in walk_objects(data) if is_goat_row(obj)]
        if rows:
            all_candidates.extend(rows)

    target = [row for row in all_candidates if is_16_20_row(row)]
    if not target:
        raise RuntimeError("MLA Eastern States goat OTH 16–20kg cwt indicator not found")

    target.sort(key=date_key, reverse=True)
    for row in target:
        price = number_from_obj(row)
        if price is not None and 0 < price < 2000:
            print(f"MLA Eastern States goat OTH 16–20kg row: {row}")
            return round(price, 1)
    raise RuntimeError("MLA Eastern States goat OTH 16–20kg price not found")


def update_xml(price):
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    display_price = f"{price:g} c/kg cwt"
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Eastern States Goat OTH Price</title>
    <link>{MLA_STATISTICS_URL}</link>
    <description>Latest MLA Eastern States goat Over-the-Hooks indicator</description>
    <language>en-au</language>
    <item>
      <title>Eastern States Goat OTH — 16–20kg cwt</title>
      <link>{MLA_STATISTICS_URL}</link>
      <guid>eastern-states-goat-oth-16-20kg</guid>
      <pubDate>{now}</pubDate>
      <description><![CDATA[
        <p><strong>Price:</strong> {display_price}</p>
        <p><strong>Category:</strong> Eastern States 16–20kg cwt</p>
        <p><strong>Source:</strong> MLA Statistics API</p>
      ]]></description>
    </item>
  </channel>
</rss>'''
    OUTPUT_FILE.write_text(xml, encoding="utf-8")


if __name__ == "__main__":
    try:
        price = fetch_goat_price()
        print(f"MLA goat OTH: {price:g} c/kg cwt")
        update_xml(price)
    except Exception as error:
        if OUTPUT_FILE.exists():
            print("Goat update failed; retaining last known price:", error)
        else:
            raise
