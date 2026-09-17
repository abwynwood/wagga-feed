import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

AGORA_URL = "https://buyer.agoralivestock.com.au/marketplace"
OUTPUT_FILE = Path(__file__).with_name("goats.xml")


def fetch_bourke_grid():
    response = requests.get(
        AGORA_URL,
        timeout=30,
        headers={"User-Agent": "wagga-feed/1.0"},
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    pattern = re.compile(
        r"Bourke\s+Goat\s+Grid\s+(\d+)\s*\(([^)]*)\)(.{0,220}?)\$(\d+(?:\.\d+)?)\s*/kg\s*HSCW",
        re.I,
    )
    matches = []
    for match in pattern.finditer(text):
        grid_number = int(match.group(1))
        date_text = match.group(2).strip()
        price_dollars = float(match.group(4))
        matches.append((grid_number, date_text, price_dollars))

    if not matches:
        raise RuntimeError("Current Bourke goat processor grid not found on Agora marketplace")

    grid_number, date_text, price_dollars = max(matches, key=lambda item: item[0])
    price_cents = round(price_dollars * 100, 1)
    print(f"Agora Bourke goat grid {grid_number} ({date_text}): ${price_dollars:g}/kg HSCW = {price_cents:g} c/kg cwt")
    return price_cents, grid_number, date_text


def update_xml(price_cents, grid_number, date_text):
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Bourke Goat Processor Grid</title>
    <link>{AGORA_URL}</link>
    <description>Current Thomas Foods International Bourke goat processor grid published by Agora Livestock</description>
    <language>en-au</language>
    <item>
      <title>Bourke Goat Grid {grid_number} ({date_text})</title>
      <link>{AGORA_URL}</link>
      <guid>bourke-goat-grid</guid>
      <pubDate>{now}</pubDate>
      <description><![CDATA[
        <p><strong>Price:</strong> {price_cents:g} c/kg cwt</p>
        <p><strong>Grid:</strong> Bourke Goat Grid {grid_number} ({date_text})</p>
        <p><strong>Processor:</strong> Thomas Foods International, Bourke</p>
        <p><strong>Source:</strong> Agora Livestock</p>
      ]]></description>
    </item>
  </channel>
</rss>'''
    OUTPUT_FILE.write_text(xml, encoding="utf-8")


if __name__ == "__main__":
    try:
        price_cents, grid_number, date_text = fetch_bourke_grid()
        update_xml(price_cents, grid_number, date_text)
    except Exception as error:
        print("Goat update failed:", error)
        raise
