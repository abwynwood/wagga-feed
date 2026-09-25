#!/usr/bin/env python3
import html
import re
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from time import time
from playwright.sync_api import sync_playwright

SOURCE_URL = "https://agoralivestock.com.au/saleyard-griffith-sheep/"
OUTPUT_FILE = Path(__file__).with_name("griffith.xml")
HISTORY_FILE = Path(__file__).with_name("griffith_history.json")

def get_page(url=SOURCE_URL):
    separator = "&" if "?" in url else "?"
    fresh_url = f"{url}{separator}wagga_feed_ts={int(time())}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (compatible; wagga-feed/1.0)"
        )
        page.goto(fresh_url, wait_until="networkidle", timeout=60000)

        # The Griffith results are published in Google Sheets iframes further
        # down the Agora page. Capture every rendered iframe and look for the
        # structured results table there.
        frames = [page.main_frame] + list(page.frames)
        frame_html = []
        frame_text = []

        for frame in frames:
            try:
                html_content = frame.content()
                text_content = frame.locator("body").inner_text(timeout=5000)
                frame_html.append(html_content)
                frame_text.append(text_content)
            except Exception:
                continue

        main_html = page.content()
        main_text = page.locator("body").inner_text(timeout=10000)

        browser.close()

    return main_html, main_text, frame_html, frame_text


def get_text(url=SOURCE_URL):
    return get_page(url)[1]

def find(pattern, text):
    return re.search(pattern, text, re.IGNORECASE | re.DOTALL)

def money_range(low, high):
    low, high = sorted((int(low.replace(",", "")), int(high.replace(",", ""))))
    return "$%s/hd – $%s/hd" % (f"{low:,}", f"{high:,}")

def single_money(value):
    return "$%s/hd" % f"{int(value.replace(',', '')):,}"

def range_from_match(match):
    return money_range(match.group(1), match.group(2))

def first_range(patterns, text):
    for pattern in patterns:
        match = find(pattern, text)
        if match:
            return range_from_match(match)
    return "Not reported"

def first_single(patterns, text):
    for pattern in patterns:
        match = find(pattern, text)
        if match:
            return single_money(match.group(1))
    return "Not reported"

def mutton_or_ewes_range(text):
    anchors = list(re.finditer(r"\bmutton\b|\bewes?\b", text, re.I))
    if not anchors:
        return "Not reported"
    for anchor in anchors:
        section = text[anchor.start():anchor.start() + 900]
        values = [int(v.replace(",", "")) for v in re.findall(r"(?:reaching|reached|sold\s+to|sold\s+for|made|topped\s+at)\s+\$([\d,]+)", section, re.I)]
        if len(values) >= 2:
            return money_range(str(min(values)), str(max(values)))
        if len(values) == 1:
            return single_money(str(values[0]))
        result = first_range([r"ranged\s+between\s+\$([\d,]+)\s+and\s+\$([\d,]+)", r"ranged\s+from\s+\$([\d,]+)\s+to\s+\$([\d,]+)"], section)
        if result != "Not reported":
            return result
    return "Not reported"

def market_direction(text):
    if re.search(r"\b(stronger|firmer|dearer|strengthened|gained momentum|strong buyer|strong demand)\b", text, re.I):
        return "FIRM"
    if re.search(r"\b(softer|cheaper|easier|eased|weaker|weakened)\b", text, re.I):
        return "SOFTER"
    return "STEADY"

def load_previous_categories(current_date):
    try:
        history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else {}
        dates = sorted((date for date in history if date < current_date), reverse=True)
        return history.get(dates[0], {}) if dates else {}
    except Exception:
        return {}

def save_category_history(sale_date, values):
    try:
        history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else {}
    except Exception:
        history = {}
    history[sale_date] = {k: v for k, v in values.items() if v is not None}
    keep = sorted(history)[-20:]
    HISTORY_FILE.write_text(json.dumps({k: history[k] for k in keep}, indent=2), encoding="utf-8")

def comparison_arrow(current, previous):
    if previous is None:
        return "➡️ $0/hd"
    change=round(current-previous)
    if change>0:
        return "⬆️ $" + str(change) + "/hd"
    if change<0:
        return "⬇️ $" + str(abs(change)) + "/hd"
    return "➡️ $0/hd"

def section_between(text, starts, ends):
    start = None
    for pattern in starts:
        match = re.search(pattern, text, re.I)
        if match:
            start = match.start()
            break
    if start is None:
        return ""
    end = len(text)
    for pattern in ends:
        match = re.search(pattern, text[start + 1:], re.I)
        if match:
            end = min(end, start + 1 + match.start())
    return text[start:end]


# These are the fixed Dakboard categories. The table data changes each week,
# but these labels and filters stay the same unless we deliberately change them.
TABLE_CATEGORIES = [
    {
        "label": "Dorper Ewes",
        "category": "Ewe",
        "sale_prefix": "Dorper",
        "min_weight": None,
        "max_weight": None,
    },
    {
        "label": "Dorper Hoggets",
        "category": "Hogget",
        "sale_prefix": "Dorper",
        "min_weight": None,
        "max_weight": None,
    },
    {
        "label": "Dorper Lambs 20-26kg",
        "category": "Lamb",
        "sale_prefix": "Dorper",
        "min_weight": 20.1,
        "max_weight": 26.0,
    },
]


def clean_cell(value):
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def weight_bounds(weight_text):
    value = clean_cell(weight_text).replace("kg", "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", value)
    if match:
        return float(match.group(1)), float(match.group(2))
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\.1\+", value)
    if match:
        # 22.1+ means the lower bound is 22.1 with no upper bound.
        return float(match.group(1)) + 0.1, None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\+", value)
    if match:
        return float(match.group(1)), None
    return None, None


def parse_results_table(frame_html, frame_text):
    """
    Parse the Google Sheets results table rendered inside Agora's iframe.
    We inspect all frames because Agora can change which published sheet
    contains the current Griffith results.
    """
    records = []

    for html_content, text_content in zip(frame_html, frame_text):
        if "Griffith results" not in text_content:
            continue
        soup = BeautifulSoup(html_content, "html.parser")

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue

            current_category = ""
            current_prefix = ""

            for row in rows:
                cells = [
                    clean_cell(cell.get_text(" ", strip=True))
                    for cell in row.find_all(["td", "th"])
                ]
                if len(cells) < 9:
                    continue

                joined = " | ".join(cells)
                if "Category" in joined and "$ / head" in joined:
                    continue

                category = cells[0] or current_category
                prefix = cells[1] or current_prefix

                # Google Sheets may render blank cells as inherited visually.
                if category:
                    current_category = category
                if prefix:
                    current_prefix = prefix

                if not current_category or not current_prefix:
                    continue

                min_price = re.sub(r"[^0-9]", "", cells[6])
                max_price = re.sub(r"[^0-9]", "", cells[8])
                if not min_price or not max_price:
                    continue

                low_weight, high_weight = weight_bounds(cells[2])

                records.append({
                    "category": current_category,
                    "sale_prefix": current_prefix,
                    "weight_low": low_weight,
                    "weight_high": high_weight,
                    "price_min": int(min_price),
                    "price_max": int(max_price),
                })

    results = {}
    for spec in TABLE_CATEGORIES:
        selected = []

        for record in records:
            if record["category"].lower() != spec["category"].lower():
                continue
            if record["sale_prefix"].lower() != spec["sale_prefix"].lower():
                continue

            if spec["min_weight"] is not None:
                if record["weight_low"] is None:
                    continue
                # Include rows whose range overlaps 20.1-26.0kg.
                if record["weight_high"] is not None:
                    if record["weight_high"] < spec["min_weight"] or record["weight_low"] > spec["max_weight"]:
                        continue
                elif record["weight_low"] > spec["max_weight"]:
                    continue

            selected.append(record)

        if selected:
            results[spec["label"]] = (
                min(r["price_min"] for r in selected),
                max(r["price_max"] for r in selected),
            )
        else:
            results[spec["label"]] = None

    return results


def display_table_range(value_range):
    if value_range is None:
        return "Not reported"
    low, high = value_range
    return single_money(str(low)) if low == high else money_range(str(low), str(high))


def table_category_value(value_range):
    if value_range is None:
        return None
    return (value_range[0] + value_range[1]) / 2


def category_value(table_results, label):
    return table_category_value(table_results.get(label))


def yarding_comparison(current, previous):
    if current is None or previous is None:
        return "➡️ 0 head"
    change = round(current - previous)
    if change > 0:
        return f"⬆️ {change:,} head"
    if change < 0:
        return f"⬇️ {abs(change):,} head"
    return "➡️ 0 head"


def main():
    main_html, text, frame_html, frame_text = get_page()
    date_match = find(r"Report Date:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})", text)
    yarding_match = find(r"Total Yarding:\s*([\d,]+)", text)
    if not date_match or not yarding_match:
        raise RuntimeError("Agora Griffith date/yarding not found")

    sale_date = date_match.group(1)
    previous = load_previous_categories(sale_date)
    table_results = parse_results_table(frame_html, frame_text)

    current_values = {
        spec["label"]: category_value(table_results, spec["label"])
        for spec in TABLE_CATEGORIES
    }

    current_yarding = int(yarding_match.group(1).replace(",", ""))
    previous_yarding = previous.get("Yarding")
    yarding_change = yarding_comparison(current_yarding, previous_yarding)

    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "Griffith Sheep Sale"
    ET.SubElement(channel, "link").text = SOURCE_URL
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = "Griffith Sheep Sale — " + date_match.group(1)

    lines = []
    for spec in TABLE_CATEGORIES:
        label = spec["label"]
        display = display_table_range(table_results.get(label))
        value = current_values[label]
        change = comparison_arrow(value, previous.get(label)) if value is not None else "➡️ $0/hd"
        lines.append(f"<br><b>{label}:</b> {display} ({change})")

    lines.append(
        "<br><i>Yarding: " + yarding_match.group(1) + " head (" + yarding_change + ")</i>"
    )
    description = "\\n".join(lines)

    ET.SubElement(item, "description").text = description
    ET.SubElement(item, "pubDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    ET.SubElement(item, "guid").text = SOURCE_URL
    ET.ElementTree(root).write(OUTPUT_FILE, encoding="utf-8", xml_declaration=True)

    history_values = {label: value for label, value in current_values.items() if value is not None}
    history_values["Yarding"] = current_yarding
    save_category_history(sale_date, history_values)

    xml = OUTPUT_FILE.read_text(encoding="utf-8")
    escaped_description = description.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    xml = xml.replace(
        "<description>" + escaped_description + "</description>",
        "<description><![CDATA[" + description.replace("\\n", "<br>") + "]]></description>",
    )
    OUTPUT_FILE.write_text(xml, encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if OUTPUT_FILE.exists():
            print("Update failed; retaining previous feed:", error)
        else:
            raise
