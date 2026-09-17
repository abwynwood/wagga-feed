import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

AGORA_URL = "https://buyer.agoralivestock.com.au/marketplace"
MLA_STATISTICS_URL = "https://www.mla.com.au/prices-markets/statistics/australian-goat-oth/"
OUTPUT_FILE = Path(__file__).with_name("goats.xml")


def fetch_bourke_grid():
    response = requests.get(AGORA_URL, timeout=30, headers={"User-Agent": "wagga-feed/1.0"})
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    matches = []
    pattern = re.compile(
        r"Bourke\s+Goat\s+Grid\s+(\d+)\s*\(([^)]*)\).*?\$(\d+(?:\.\d+)?)\s*/kg\s*HSCW",
        re.I,
    )
    for match in pattern.finditer(text):
        matches.append((int(match.group(1)), match.group(2).strip(), float(match.group(3))))

    if not matches:
        fallback = re.compile(r"Bourke\s+Goat\s+Grid\s+(\d+)\s*\(([^)]*)\)", re.I)
        for match in fallback.finditer(text):
            window = text[max(0, match.start() - 700): min(len(text), match.end() + 700)]
            price_match = re.search(r"\$(\d+(?:\.\d+)?)\s*/kg\s*HSCW", window, re.I)
            if price_match:
                matches.append((int(match.group(1)), match.group(2).strip(), float(price_match.group(1))))

    if not matches:
        raise RuntimeError("Current Bourke goat processor grid not found on Agora marketplace")

    grid_number, date_text, price_dollars = max(matches, key=lambda item: item[0])
    price_cents = round(price_dollars * 100, 1)
    print(f"Agora Bourke goat grid {grid_number} ({date_text}): ${price_dollars:g}/kg HSCW = {price_cents:g} c/kg cwt")
    return price_cents, grid_number, date_text


def update_xml(price_cents, grid_number, date_text):
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    display_price = f"{price_cents:g} c/kg cwt"
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
        <p><strong>Price:</strong> {display_price}</p>
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
