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

def get_text(url=SOURCE_URL):
    response = requests.get(url, timeout=30, headers={"User-Agent": "wagga-feed/1.0"})
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

def parse_categories(text):
    restocker = first_single([
        r"(?:new\s+season\s+)?store\s+lambs?\s+to\s+\d+\s*kg\s+sold\s+to\s+\$([\d,]+)",
        r"(?:new\s+season\s+)?store\s+lambs?\s+to\s+\d+\s*kg[^.]{0,120}?\$([\d,]+)\s*/?\s*(?:head|hd)",
        r"restocker\s+lambs?[^.]{0,160}?(?:from\s+\$([\d,]+)\s+to\s+\$([\d,]+))",
    ], text)
    trade = first_range([
        r"trade\s+weights?\s+\d+\s*to\s*\d+\s*kg\s+(?:sold|ranged)\s+(?:from\s+)?\$([\d,]+)\s+(?:to|-)\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
        r"trade\s+weights?[^.]{0,160}?\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
        r"trade\s+lambs?\s+sold\s+from\s+\$([\d,]+)\s+to\s+\$([\d,]+)",
    ], text)
    heavy = first_range([
        r"heavy\s+weights?\s+\$([\d,]+)\s+to\s+\$([\d,]+)\s*/?\s*(?:head|hd)",
        r"heavy\s+lambs?[^.]{0,180}?(?:from|ranged\s+from)\s+\$([\d,]+)\s+to\s+\$([\d,]+)",
    ], text)
    mutton = mutton_or_ewes_range(text)
    return restocker, trade, heavy, mutton

def main():
    text = get_text()
    date_match = find(r"Report Date:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})", text)
    yarding_match = find(r"Total Yarding:\s*([\d,]+)", text)
    if not date_match or not yarding_match:
        raise RuntimeError("Agora Griffith date/yarding not found")
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
    market = market_direction(text)
    summary = {"FIRM": "Prices firm to stronger.", "SOFTER": "Prices softer across the market.", "STEADY": "Prices mostly steady."}[market]
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "Griffith Sheep Sale"
    ET.SubElement(channel, "link").text = SOURCE_URL
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = "Griffith Sheep Sale — " + date_match.group(1)
    description = "\n".join([
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
