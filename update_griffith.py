#!/usr/bin/env python3
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://agoralivestock.com.au/saleyard-griffith-sheep/"
OUTPUT_FILE = Path(__file__).with_name("griffith.xml")


def get_text():
    response = requests.get(SOURCE_URL, timeout=30, headers={"User-Agent": "wagga-feed/1.0"})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    return re.sub(r"\s+", " ", html.unescape(soup.get_text(" ", strip=True))).strip()


def find(pattern, text):
    return re.search(pattern, text, re.IGNORECASE | re.DOTALL)


def money_range(low, high):
    low, high = sorted((int(low.replace(",", "")), int(high.replace(",", ""))))
    return "$%s/hd – $%s/hd" % (f"{low:,}", f"{high:,}")


def money_range_from_match(match):
    return money_range(match.group(1), match.group(2))


def first_money_range(patterns, text):
    for pattern in patterns:
        m = find(pattern, text)
        if m:
            return money_range_from_match(m)
    return "Not reported"


def single_money(patterns, text):
    for pattern in patterns:
        m = find(pattern, text)
        if m:
            return "$%s/hd" % f"{int(m.group(1).replace(',', '')):,}"
    return "Not reported"


def section_after(text, headings, stops):
    """Return the text belonging to one category, stopping at the next category."""
    start = None
    for heading in headings:
        m = find(heading, text)
        if m and (start is None or m.start() < start.start()):
            start = m
    if not start:
        return ""

    section = text[start.end():]
    end_positions = []
    for stop in stops:
        m = find(stop, section)
        if m:
            end_positions.append(m.start())
    if end_positions:
        section = section[:min(end_positions)]
    return section


def category_price(section, patterns):
    return first_money_range(patterns, section)


def mutton_or_ewes_range(text):
    """Mutton and ewes are the same DAKboard category; accept either heading."""
    section = section_after(
        text,
        [r"\bmutton\b", r"\bewes?\b"],
        [r"yarding\b", r"market reporter\b", r"summary:\b"],
    )
    if not section:
        return "Not reported"

    patterns = [
        r"ranged\s+between\s+\$([\d,]+)\s+and\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
        r"ranged\s+from\s+\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
        r"(?:most|mutton|ewes?)[^.]{0,180}?\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
        r"(?:crossbred|first\s+cross)[^.]{0,120}?(?:reached|sold\s+to)\s+\$([\d,]+)[^.]{0,120}?(?:Merino|merinos?)[^.]{0,100}?(?:reached|sold\s+to)\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
    ]
    return category_price(section, patterns)


def market_direction(text):
    if re.search(r"\b(stronger|firmer|dearer|strengthened|gained momentum|strong buyer|strong demand)\b", text, re.I):
        return "FIRM"
    if re.search(r"\b(softer|cheaper|easier|eased|weaker|weakened)\b", text, re.I):
        return "SOFTER"
    return "STEADY"


def main():
    text = get_text()
    date_match = find(r"Report Date:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})", text)
    yarding_match = find(r"Total Yarding:\s*([\d,]+)", text)
    if not date_match or not yarding_match:
        raise RuntimeError("Agora Griffith date/yarding not found")

    # Each category is extracted from its own section. This is deliberately
    # stricter than searching for the first dollar range after "lambs", because
    # the Griffith report often discusses several lamb classes in one paragraph.
    category_stops = [
        r"\btrade\s+(?:weight\s+)?lambs?\b",
        r"\btrade\s+to\s+(?:heavy\s+)?lambs?\b",
        r"\bheavy\s+(?:weight\s+)?lambs?\b",
        r"\bextra\s+heavy\b",
        r"\bsuper\s+heavy\b",
        r"\bmutton\b",
        r"\bewes?\b",
        r"\byarding\b",
        r"\bmarket reporter\b",
    ]

    restocker_section = section_after(
        text,
        [r"\brestocker\s+lambs?\b", r"\brestockers?\b", r"\bstore\s+lambs?\b"],
        [s for s in category_stops if not re.search(r"restocker|store", s, re.I)],
    )
    restocker = category_price(restocker_section, [
        r"(?:sold|selling|made|returned)\s+(?:from\s+)?\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
        r"ranged\s+from\s+\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
    ])

    trade_section = section_after(
        text,
        [r"\btrade\s+(?:weight\s+)?lambs?\b", r"\btrade\s+to\s+(?:heavy\s+)?lambs?\b"],
        [r"\bheavy\s+(?:weight\s+)?lambs?\b", r"\bextra\s+heavy\b", r"\bsuper\s+heavy\b", r"\bmutton\b", r"\bewes?\b", r"\byarding\b"],
    )
    trade = category_price(trade_section, [
        r"ranged\s+from\s+\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
        r"(?:sold|selling|made|returned)\s+(?:from\s+)?\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
    ])

    heavy_section = section_after(
        text,
        [r"\bheavy\s+(?:weight\s+)?lambs?\b", r"\bheavy\s+to\s+heavy\s+lambs?\b"],
        [r"\bmutton\b", r"\bewes?\b", r"\byarding\b", r"\bmarket reporter\b"],
    )
    heavy = category_price(heavy_section, [
        r"ranged\s+from\s+\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
        r"(?:sold|selling|made|returned)\s+(?:from\s+)?\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
    ])

    mutton = mutton_or_ewes_range(text)

    # If the sale page has not yet exposed a separate category price, consult
    # the same-date market summary. Never use an older report to fill a value.
    try:
        raw_date = date_match.group(1)
        clean_date = re.sub(r"(st|nd|rd|th)", "", raw_date)
        dt = datetime.strptime(clean_date, "%d %B %Y")
        slug = dt.strftime("%-d-%B-%Y").lower()
        summary_url = f"https://agoralivestock.com.au/sheep-market-summary-{slug}/"
        summary_response = requests.get(summary_url, timeout=30, headers={"User-Agent": "wagga-feed/1.0"})
        if summary_response.ok:
            summary_soup = BeautifulSoup(summary_response.text, "html.parser")
            summary_text = re.sub(r"\s+", " ", html.unescape(summary_soup.get_text(" ", strip=True))).strip()
            if restocker == "Not reported":
                restocker_section = section_after(summary_text, [r"\brestocker\s+lambs?\b", r"\brestockers?\b", r"\bstore\s+lambs?\b"], [r"\btrade\b", r"\bheavy\b", r"\bmutton\b", r"\bewes?\b"])
                restocker = category_price(restocker_section, [r"(?:from|to)\s+\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)", r"sold\s+from\s+\$([\d,]+)\s+to\s+\$([\d,]+)"])
            if trade == "Not reported":
                trade_section = section_after(summary_text, [r"\btrade\s+(?:weight\s+)?lambs?\b", r"\btrade\b"], [r"\bheavy\b", r"\bmutton\b", r"\bewes?\b"])
                trade = category_price(trade_section, [r"ranged\s+from\s+\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)", r"sold\s+from\s+\$([\d,]+)\s+to\s+\$([\d,]+)"])
            if heavy == "Not reported":
                heavy_section = section_after(summary_text, [r"\bheavy\s+(?:weight\s+)?lambs?\b", r"\bheavy\b"], [r"\bmutton\b", r"\bewes?\b"])
                heavy = category_price(heavy_section, [r"ranged\s+from\s+\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)", r"sold\s+from\s+\$([\d,]+)\s+to\s+\$([\d,]+)"])
            if mutton == "Not reported":
                mutton = mutton_or_ewes_range(summary_text)
    except Exception:
        pass

    market = market_direction(text)
    summary = {"FIRM": "Prices firm to stronger.", "SOFTER": "Prices softer across the market.", "STEADY": "Prices mostly steady."}[market]

    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "Griffith Sheep Sale"
    ET.SubElement(channel, "link").text = SOURCE_URL
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = "Griffith Sheep Sale — " + date_match.group(1)
    description = "\n".join([
        "GRIFFITH SHEEP SALE — " + date_match.group(1), "",
        "Restocker Lambs Range: " + restocker,
        "Trade Lambs Range: " + trade,
        "Heavy Lambs Range: " + heavy,
        "Mutton/Ewes Range: " + mutton,
        "Yarding: " + yarding_match.group(1) + " head",
        "Market: " + market,
        "Summary: " + summary,
    ])
    ET.SubElement(item, "description").text = description
    ET.SubElement(item, "pubDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    ET.SubElement(item, "guid").text = SOURCE_URL

    ET.ElementTree(root).write(OUTPUT_FILE, encoding="utf-8", xml_declaration=True)
    xml = OUTPUT_FILE.read_text(encoding="utf-8")
    escaped_description = description.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    xml = xml.replace(
        "<description>" + escaped_description + "</description>",
        "<description><![CDATA[" + description.replace("\n", "<br>") + "]]></description>",
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
