import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

API_BASE = "https://api-mlastatistics.mla.com.au"
MLA_STATISTICS_URL = "https://www.mla.com.au/prices-markets/statistics/"
OUTPUT_FILE = Path(__file__).with_name("goats.xml")

HEADERS = {"User-Agent": "wagga-feed/1.0", "Accept": "application/json"}


def get_json(path, params=None):
    response = requests.get(
        API_BASE + path,
        params=params,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def walk_objects(value):
    """Yield every dict nested inside an API response."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_objects(child)


def text_of(obj):
    return " ".join(str(v) for v in obj.values() if isinstance(v, (str, int, float)))


def find_goat_oth_indicator_id():
    data = get_json("/indicator")
    candidates = []

    for obj in walk_objects(data):
        text = text_of(obj).lower()
        if "goat" not in text:
            continue
        if not any(term in text for term in ("over the hooks", "oth", "over-the-hooks")):
            continue

        identifier = None
        for key, value in obj.items():
            key_l = str(key).lower()
            if key_l in {"id", "indicatorid", "indicator_id", "indicatorid"} and isinstance(value, (int, str)):
                identifier = value
                break

        if identifier is not None:
            candidates.append((identifier, text))

    if not candidates:
        raise RuntimeError("MLA API goat OTH indicator was not found")

    # Prefer an indicator explicitly describing the 12.1–16 kg goat series.
    for identifier, text in candidates:
        if "12.1" in text and "16" in text:
            return identifier
    return candidates[0][0]


def extract_rows(data):
    rows = []
    for obj in walk_objects(data):
        text = text_of(obj).lower()
        if "goat" in text or "12.1" in text or "16.1" in text or "16-20" in text:
            rows.append(obj)
    return rows


def number_from_obj(obj, preferred):
    for wanted in preferred:
        for key, value in obj.items():
            if str(key).lower() == wanted and isinstance(value, (int, float)):
                return float(value)
            if str(key).lower() == wanted and isinstance(value, str):
                match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
                if match:
                    return float(match.group(0))
    return None


def date_key(obj):
    for key, value in obj.items():
        if "date" in str(key).lower() or "period" in str(key).lower():
            if isinstance(value, str):
                match = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", value)
                if match:
                    return match.group(0)
    return ""


def fetch_goat_price():
    indicator_id = find_goat_oth_indicator_id()

    # The statistics API has evolved over time. Try the documented report with
    # the common parameter spellings, then fall back to the unfiltered report.
    attempts = [
        {"indicatorId": indicator_id},
        {"indicator_id": indicator_id},
        {"indicator": indicator_id},
        None,
    ]

    for params in attempts:
        try:
            data = get_json("/report/5", params=params)
        except requests.RequestException:
            continue

        rows = extract_rows(data)
        if not rows:
            continue

        # Prefer the 12.1–16kg cwt series, which is the standard goat OTH
        # benchmark used by MLA and industry reporting.
        target_rows = []
        for row in rows:
            text = text_of(row).lower().replace(" ", "")
            if "12.1" in text and "16" in text:
                target_rows.append(row)

        if not target_rows:
            target_rows = rows

        # Choose the latest dated record available.
        target_rows.sort(key=date_key, reverse=True)
        for row in target_rows:
            price = number_from_obj(
                row,
                ("average", "avg", "averageprice", "avgprice", "price"),
            )
            if price is not None and 0 < price < 2000:
                return round(price, 1)

    raise RuntimeError("MLA goat OTH price not found in Statistics API")


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
      <title>Eastern States Goat OTH — 12.1–16kg cwt</title>
      <link>{MLA_STATISTICS_URL}</link>
      <guid>eastern-states-goat-oth-12-1-16kg</guid>
      <pubDate>{now}</pubDate>
      <description><![CDATA[
        <p><strong>Price:</strong> {display_price}</p>
        <p><strong>Category:</strong> Eastern States 12.1–16kg cwt</p>
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
        # Never replace a valid feed with an error or an unverified value.
        if OUTPUT_FILE.exists():
            print("Goat update failed; retaining last known price:", error)
        else:
            raise
