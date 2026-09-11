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


def money_range_from_match(match):
    low = int(match.group(1).replace(",", ""))
    high = int(match.group(2).replace(",", ""))
    return "$%s/hd – $%s/hd" % (f"{low:,}", f"{high:,}")


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


def category_range(text, category_patterns, stop_patterns, range_patterns):
    """Search only inside one sheep category to prevent cross-category matches."""
    category = None
    for pattern in category_patterns:
        m = find(pattern, text)
        if m:
            category = m
            break
    if not category:
        return "Not reported"

    tail = text[category.end():]
    for stop_pattern in stop_patterns:
        m = find(stop_pattern, tail)
        if m:
            tail = tail[:m.start()]
    return first_money_range(range_patterns, tail)


def top_value(patterns, text):
    for pattern in patterns:
        m = find(pattern, text)
        if m:
            return "$%s/hd" % f"{int(m.group(1).replace(',', '')):,}"
    return "Not reported"


def market_direction(text):
    if re.search(r"\b(stronger|firmer|dearer|strengthened|gained momentum|strong buyer|strong demand)\b", text, re.I):
        return "FIRM"
    if re.search(r"\b(softer|cheaper|easier|eased|weaker|weakened)\b", text, re.I):
        return "SOFTER"
    return "STEADY"


def mutton_or_ewes_range(text):
    """Find the mutton/ewes category regardless of which heading the source uses."""
    return category_range(
        text,
        [r"\bmutton\b", r"\bewes?\b"],
        [r"yarding"],
        [
            r"(?:mutton|ewes?)[^.]{0,350}?crossbred\s+ewes?\s+reaching\s+\$([\d,]+)[^.]{0,120}?bare\s+shorn\s+Merino\s+ewes?\s+reaching\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
            r"(?:mutton|ewes?)[^.]{0,350}?ranged\s+between\s+\$([\d,]+)\s+and\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
            r"(?:mutton|ewes?)[^.]{0,250}?ranged\s+from\s+\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
        ],
    )


def main():
    text = get_text()
    date_match = find(r"Report Date:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})", text)
    yarding_match = find(r"Total Yarding:\s*([\d,]+)", text)
    if not date_match or not yarding_match:
        raise RuntimeError("Agora Griffith date/yarding not found")

    # The Griffith report is prose rather than a table. Parse each category
    # from the wording used in the current sale report, rather than searching
    # for a generic "range" after the word lambs. Generic matching caused the
    # same trade range to be copied into every lamb category on DAKboard.
    category_markers = [
        r"restockers+lambs?",
        r"stores+lambs?",
        r"trades+lambs?",
        r"heavys+lambs?",
        r"mutton",
        r"ewes?",
    ]
    if sum(bool(find(pattern, text)) for pattern in category_markers) < 3:
        raise RuntimeError("Agora Griffith sheep category headings not recognised; retaining previous complete sale")

    # Keep each sheep category isolated. Agora often puts several categories
    # in the same paragraph, so broad regexes can otherwise copy one category's
    # range into another.
    stops = [
        r"trade\s+lambs?",
        r"heavy\s+lambs?",
        r"extra\s+heavy",
        r"super\s+heavy",
        r"mutton",
        r"yarding",
    ]
    range_patterns = [
        r"(?:ranged\s+)?from\s+\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
        r"range\s+of\s+\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
    ]

    light_lambs = category_range(
        text,
        [r"restockers?", r"store\s+lambs?"],
        stops,
        range_patterns,
    )

    # Agora reports Restocker and Trade lambs together at Griffith.
    # Use the same reported range for both categories rather than trying to
    # scrape Trade separately (which can incorrectly return "Not reported").
    trade_lambs = light_lambs

    heavy_lambs_range = category_range(
        text,
        [r"heavy\s+lambs?"],
        [r"extra\s+heavy", r"super\s+heavy", r"heavy\s+merinos?", r"mutton", r"ewes?", r"yarding"],
        range_patterns,
    )

    heavy_lambs_top = top_value([
        r"heavy\s+lambs?[^.]{0,300}?(?:reached|topped\s+at|topped)\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
        r"(?:super|supper)\s+heavy[^.]{0,220}?(?:reached|topped\s+at|topped)\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
    ], text)

    mutton = mutton_or_ewes_range(text)

    # Agora's Griffith page can lag behind the matching market-summary page.
    # Use it only to fill fields for THIS SAME report date. We never carry an
    # individual price forward from an older sale.
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
            if light_lambs == "Not reported":
                light_lambs = category_range(summary_text, [r"restockers?", r"store\s+lambs?"], stops, range_patterns)
            if light_lambs == "Not reported":
                light_lambs = category_range(summary_text, [r"restockers?", r"store\s+lambs?"], stops, range_patterns)
            # Restocker and Trade are the same reported category/price at Griffith.
            trade_lambs = light_lambs
            if heavy_lambs_range == "Not reported":
                heavy_lambs_range = category_range(summary_text, [r"heavy\s+lambs?"], [r"extra\s+heavy", r"super\s+heavy", r"heavy\s+merinos?", r"mutton", r"ewes?", r"yarding"], range_patterns)
            if mutton == "Not reported":
                mutton = mutton_or_ewes_range(summary_text)
            if heavy_lambs_top == "Not reported":
                heavy_lambs_top = top_value([
                    r"heavy\s+lambs?[^.]{0,300}?(?:reached|topped\s+at|topped)\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
                    r"(?:super|supper)\s+heavy[^.]{0,220}?(?:reached|topped\s+at|topped)\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
                ], summary_text)
    except Exception:
        pass

    if heavy_lambs_range != "Not reported":
        heavy_lambs_value = heavy_lambs_range
        heavy_lambs_label = "Heavy Lambs Range: "
    else:
        heavy_lambs_value = heavy_lambs_top
        heavy_lambs_label = "Heavy Lambs Top: "

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
        "Restocker Lambs Range: " + light_lambs,
        "Trade Lambs Range: " + trade_lambs,
        heavy_lambs_label + heavy_lambs_value,
        "Mutton/Ewes Range: " + mutton,
        "Yarding: " + yarding_match.group(1) + " head",
        "Market: " + market,
        "Summary: " + summary,
    ])
    ET.SubElement(item, "description").text = description
    ET.SubElement(item, "pubDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    ET.SubElement(item, "guid").text = SOURCE_URL

    # DAKboard's RSS renderer collapses ordinary newlines, so use HTML breaks.
    ET.ElementTree(root).write(OUTPUT_FILE, encoding="utf-8", xml_declaration=True)
    xml = OUTPUT_FILE.read_text(encoding="utf-8")
    xml = xml.replace(
        "<description>" + description.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + "</description>",
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
