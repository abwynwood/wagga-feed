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
from time import time

SOURCE_URL = "https://agoralivestock.com.au/saleyard-griffith-sheep/"
OUTPUT_FILE = Path(__file__).with_name("griffith.xml")
HISTORY_FILE = Path(__file__).with_name("griffith_history.json")

def get_text(url=SOURCE_URL):
    # Agora can serve a cached copy to automated requests even after the
    # report has been updated. Cache-bust every request so the feed sees the
    # same current report that is visible on the Agora webpage.
    separator = "&" if "?" in url else "?"
    fresh_url = f"{url}{separator}wagga_feed_ts={int(time())}"
    response = requests.get(
        fresh_url,
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; wagga-feed/1.0)",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    return re.sub(r"\s+", " ", html.unescape(soup.get_text(" ", strip=True))).strip()

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


def price_range_from_section(section):
    values = [
        int(v.replace(",", ""))
        for v in re.findall(
            r"\$([\d,]+)\s*(?:/\s*(?:head|hd)|(?:head|hd)\b)",
            section,
            re.I,
        )
    ]
    if not values:
        return None
    return min(values), max(values)


def display_section_range(section):
    value_range = price_range_from_section(section)
    if value_range is None:
        return "Not reported"
    if value_range[0] == value_range[1]:
        return single_money(str(value_range[0]))
    return money_range(str(value_range[0]), str(value_range[1]))


def category_sections(text):
    restocker_section = section_between(
        text,
        [r"light\s+merinos?\s+under\s+\d+\s*kg"],
        [r"trade\s+weights?", r"heavy\s+lambs?", r"mutton\s+numbers?"],
    )
    trade_section = section_between(
        text,
        [r"trade\s+weights?"],
        [r"heavy\s+lambs?", r"mutton\s+numbers?"],
    )
    mutton_section = section_between(
        text,
        [r"mutton\s+numbers?"],
        [],
    )

    # Heavy lambs are deliberately limited to the named "heavy lambs to
    # 30kg" line. Do not accidentally include extra-heavy/super-heavy lambs.
    heavy_match = re.search(
        r"heavy\s+lambs?\s+to\s+30\s*kg.{0,180}?\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
        text,
        re.I | re.S,
    )
    heavy_section = heavy_match.group(0) if heavy_match else section_between(
        text,
        [r"heavy\s+lambs?"],
        [r"mutton\s+numbers?"],
    )

    return restocker_section, trade_section, heavy_section, mutton_section


def parse_categories(text):
    restocker_section, trade_section, heavy_section, mutton_section = category_sections(text)
    return (
        display_section_range(restocker_section),
        display_section_range(trade_section),
        display_section_range(heavy_section),
        display_section_range(mutton_section),
    )


def category_value(text, label):
    sections = category_sections(text)
    index = {
        "Restocker Lambs": 0,
        "Trade Lambs": 1,
        "Heavy Lambs": 2,
        "Mutton/Ewes": 3,
    }.get(label)
    if index is None:
        return None
    value_range = price_range_from_section(sections[index])
    if value_range is None:
        return None
    return (value_range[0] + value_range[1]) / 2


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
    text = get_text()
    date_match = find(r"Report Date:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})", text)
    yarding_match = find(r"Total Yarding:\s*([\d,]+)", text)
    if not date_match or not yarding_match:
        raise RuntimeError("Agora Griffith date/yarding not found")
    sale_date = date_match.group(1)
    previous = load_previous_categories(sale_date)
    restocker, trade, heavy, mutton = parse_categories(text)
    try:
        raw_date = date_match.group(1)
        clean_date = re.sub(r"(st|nd|rd|th)", "", raw_date)
        dt = datetime.strptime(clean_date, "%d %B %Y")
        slug = dt.strftime("%-d-%B-%Y").lower()
        summary_url = f"https://agoralivestock.com.au/sheep-market-summary-{slug}/"
        summary_response = requests.get(summary_url, timeout=30, headers={"User-Agent": "wagga-feed/1.0"})
        if summary_response.ok:
            summary_text = get_text(summary_url)
            sr, st, sh, sm = parse_categories(summary_text)
            if restocker == "Not reported": restocker = sr
            if trade == "Not reported": trade = st
            if heavy == "Not reported": heavy = sh
            if mutton == "Not reported": mutton = sm
    except Exception:
        pass
    current_values = {"Restocker Lambs": category_value(text, "Restocker Lambs"), "Trade Lambs": category_value(text, "Trade Lambs"), "Heavy Lambs": category_value(text, "Heavy Lambs"), "Mutton/Ewes": None}
    if mutton != "Not reported":
        nums=[int(x.replace(",", "")) for x in re.findall(r"\$([\d,]+)/hd", mutton)]
        if nums: current_values["Mutton/Ewes"]=sum(nums)/len(nums)
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "Griffith Sheep Sale"
    ET.SubElement(channel, "link").text = SOURCE_URL
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = "Griffith Sheep Sale — " + date_match.group(1)
    changes={label:(comparison_arrow(value,previous.get(label)) if value is not None else "➡️ $0/hd") for label,value in current_values.items()}
    current_yarding = int(yarding_match.group(1).replace(",", ""))
    previous_yarding = previous.get("Yarding")
    yarding_change = yarding_comparison(current_yarding, previous_yarding)

    description = "\n".join([
        "<br><b>Restocker Lambs:</b> " + restocker + " (" + changes["Restocker Lambs"] + ")",
        "<br><b>Trade Lambs:</b> " + trade + " (" + changes["Trade Lambs"] + ")",
        "<br><b>Heavy Lambs:</b> " + heavy + " (" + changes["Heavy Lambs"] + ")",
        "<br><b>Mutton/Ewes:</b> " + mutton + " (" + changes["Mutton/Ewes"] + ")",
        "<br><i>Yarding: " + yarding_match.group(1) + " head (" + yarding_change + ")</i>",
    ])
    ET.SubElement(item, "description").text = description
    ET.SubElement(item, "pubDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    ET.SubElement(item, "guid").text = SOURCE_URL
    ET.ElementTree(root).write(OUTPUT_FILE, encoding="utf-8", xml_declaration=True)
    current_values["Yarding"] = current_yarding
    save_category_history(sale_date, current_values)
    xml = OUTPUT_FILE.read_text(encoding="utf-8")
    escaped_description = description.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    xml = xml.replace("<description>" + escaped_description + "</description>", "<description><![CDATA[" + description.replace("\n", "<br>") + "]]></description>")
    OUTPUT_FILE.write_text(xml, encoding="utf-8")

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if OUTPUT_FILE.exists():
            print("Update failed; retaining previous feed:", error)
        else:
            raise
