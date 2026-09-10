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

def money_range(patterns, text):
    for pattern in patterns:
        m = find(pattern, text)
        if m:
            low = int(m.group(1).replace(",", ""))
            high = int(m.group(2).replace(",", ""))
            return "$%s/hd – $%s/hd" % (f"{low:,}", f"{high:,}")
    return "Not reported"

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

    light_lambs = money_range([
        r"Restockers paid from \$([\d,]+) to \$([\d,]+)/head",
        r"Restockers paid from \$([\d,]+) to \$([\d,]+)/hd",
    ], text)

    trade_lambs = money_range([
        r"trade to heavy lambs in a range of \$([\d,]+) to \$([\d,]+)/head",
        r"trade lambs?[^.]{0,100}?range of \$([\d,]+) to \$([\d,]+)/head",
    ], text)

    mutton = money_range([
        r"lighter and odd clean-up penlots from \$([\d,]+) to \$([\d,]+)/head",
        r"most sheep with frame and condition from \$([\d,]+) to \$([\d,]+)/head",
    ], text)

    top = find(r"crossbred and Dorper ewes.*?top of \$([\d,]+)/head", text)
    low = find(r"lighter and odd clean-up penlots from \$([\d,]+) to \$([\d,]+)/head", text)
    if top and low:
        mutton = "$%s/hd – $%s/hd" % (f"{int(low.group(1).replace(',', '')):,}", f"{int(top.group(1).replace(',', '')):,}")

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
        "Light Lambs: " + light_lambs,
        "Trade Lambs: " + trade_lambs,
        "Mutton: " + mutton, "",
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
