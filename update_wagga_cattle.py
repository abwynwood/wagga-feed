#!/usr/bin/env python3
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://agoralivestock.com.au/saleyard-wagga-cattle/"
OUTPUT_FILE = Path(__file__).with_name("wagga_cattle.xml")

def get_text():
    response = requests.get(SOURCE_URL, timeout=30, headers={"User-Agent": "wagga-feed/1.0"})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    return re.sub(r"\s+", " ", html.unescape(soup.get_text(" ", strip=True))).strip()

def find(pattern, text):
    return re.search(pattern, text, re.IGNORECASE | re.DOTALL)

def cents_range(patterns, text):
    values = []
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.I | re.S):
            values.extend(int(v.replace(",", "")) for v in m.groups() if v)
    if not values:
        return "Not reported"
    return "%d–%dc/kg" % (min(values), max(values))

def market_direction(text):
    if re.search(r"\b(strong|stronger|firmer|dearer|lifted|gained|competitive)\b", text, re.I):
        return "FIRM"
    if re.search(r"\b(softer|cheaper|easier|eased|weaker|declined)\b", text, re.I):
        return "SOFTER"
    return "STEADY"

def main():
    text = get_text()
    date_match = find(r"Report Date:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})", text)
    yarding_match = find(r"Total Yarding:\s*([\d,]+)", text)
    if not date_match or not yarding_match:
        raise RuntimeError("Agora Wagga cattle date/yarding not found")

    feeder = cents_range([
        r"Light feeder steers[^.]{0,120}?from ([\d,]+)\s*(?:to|-|–)\s*([\d,]+)c/kg",
        r"Medium weight feeder steers[^.]{0,120}?from ([\d,]+)\s*(?:to|-|–)\s*([\d,]+)c/kg",
        r"Heavy feeder steers[^.]{0,120}?from ([\d,]+)\s*(?:to|-|–)\s*([\d,]+)c/kg",
    ], text)

    cows = cents_range([
        r"heavy cows[^.]{0,100}?from ([\d,]+)\s*(?:to|-|–)\s*([\d,]+)c/kg",
        r"leaner cows[^.]{0,100}?from ([\d,]+)\s*(?:to|-|–)\s*([\d,]+)c/kg",
    ], text)

    market = market_direction(text)
    summary = {"FIRM": "Market firm to stronger.", "SOFTER": "Market softer.", "STEADY": "Market mostly steady."}[market]

    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "Wagga Cattle Sale"
    ET.SubElement(channel, "link").text = SOURCE_URL
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = "Wagga Cattle Sale — " + date_match.group(1)
    description = "\n".join([
        "WAGGA CATTLE SALE — " + date_match.group(1), "",
        "Feeder Steers: " + feeder,
        "Cows: " + cows, "",
        "Yarding: " + yarding_match.group(1) + " head",
        "Market: " + market,
        "Summary: " + summary,
    ])
    ET.SubElement(item, "description").text = description
    ET.SubElement(item, "pubDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    ET.SubElement(item, "guid").text = SOURCE_URL
    ET.ElementTree(root).write(OUTPUT_FILE, encoding="utf-8", xml_declaration=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if OUTPUT_FILE.exists():
            print("Update failed; retaining previous feed:", error)
        else:
            raise
