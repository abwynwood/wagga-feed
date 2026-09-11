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


def find_goat_oth_indicator_id():
    """Best-effort lookup. The report itself is also queried without an ID below."""
    data = get_json("/indicator")
    candidates = []
    id_keys = {
        "id", "indicatorid", "indicator_id", "indicatorno", "indicator_no",
        "code", "indicatorcode", "indicator_code"
    }

    for obj in walk_objects(data):
        text = text_of(obj).lower()
        if "goat" not in text:
            continue
        if not any(term in text for term in ("over the hooks", "over-the-hooks", "oth")):
            continue

        identifier = None
        for key, value in obj.items():
            if str(key).lower() in id_keys and isinstance(value, (int, str)) and str(value).strip():
                identifier = value
                break
        if identifier is not None:
            candidates.append((identifier, text))

    if not candidates:
        return None

    for identifier, text in candidates:
        compact = text.replace(" ", "")
        if "12.1" in compact and "16" in compact:
            return identifier
        if "12–16" in text or "12-16" in text:
            return identifier
    return candidates[0][0]


def number_from_obj(obj):
    preferred = (
        "average", "avg", "averageprice", "avgprice", "price",
        "value", "indicatorvalue", "indicator_value", "avgvalue", "avg_value"
    )
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
        if any(term in str(key).lower() for term in ("date", "period", "week")):
            if isinstance(value, str):
                match = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", value)
                if match:
                    return match.group(0)
    return ""


def is_target_goat_row(obj):
    text = text_of(obj).lower()
    compact = text.replace(" ", "")
    has_goat = "goat" in text
    has_weight = (
        ("12.1" in compact and "16" in compact)
        or "12-16" in compact
        or "12–16" in text
        or "12 to 16" in text
    )
    has_oth = "oth" in text or "over the hooks" in text or "over-the-hooks" in text
    return has_goat and (has_weight or has_oth)


def fetch_from_report(params):
    data = get_json("/report/5", params=params)
    candidates = [obj for obj in walk_objects(data) if is_target_goat_row(obj)]

    # Prefer the explicit 12–16kg cwt goat OTH rows.
    weighted = []
    for obj in candidates:
        text = text_of(obj).lower()
        compact = text.replace(" ", "")
        if (
            ("12.1" in compact and "16" in compact)
            or "12-16" in compact
            or "12–16" in text
            or "12 to 16" in text
        ):
            weighted.append(obj)
    if weighted:
        candidates = weighted

    candidates.sort(key=date_key, reverse=True)
    for row in candidates:
        price = number_from_obj(row)
        if price is not None and 0 < price < 2000:
            print(f"MLA goat OTH row: {row}")
            return round(price, 1)
    return None


def fetch_goat_price():
    # Do not make a failed /indicator lookup prevent the actual report lookup.
    indicator_id = None
    try:
        indicator_id = find_goat_oth_indicator_id()
    except Exception as error:
        print(f"Indicator lookup failed; continuing with report lookup: {error}")

    attempts = []
    if indicator_id is not None:
        attempts.extend([
            {"indicatorId": indicator_id},
            {"indicator_id": indicator_id},
            {"indicator": indicator_id},
        ])

    # The Statistics API report can be queried directly. Try unfiltered forms as
    # well, because the indicator reference table has changed shape over time.
    attempts.extend([
        {"page": 1, "pageSize": 100},
        {"page": 1, "page_size": 100},
        None,
    ])

    for params in attempts:
        try:
            price = fetch_from_report(params)
            if price is not None:
                return price
        except requests.RequestException as error:
            print(f"MLA report request failed for {params}: {error}")
        except Exception as error:
            print(f"MLA report parsing failed for {params}: {error}")

    raise RuntimeError("MLA goat OTH 12–16kg cwt price not found in Statistics API")


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
      <title>Eastern States Goat OTH — 12–16kg cwt</title>
      <link>{MLA_STATISTICS_URL}</link>
      <guid>eastern-states-goat-oth-12-16kg</guid>
      <pubDate>{now}</pubDate>
      <description><![CDATA[
        <p><strong>Price:</strong> {display_price}</p>
        <p><strong>Category:</strong> Eastern States 12–16kg cwt</p>
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
