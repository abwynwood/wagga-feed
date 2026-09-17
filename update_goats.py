import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

AGORA_URL = "https://buyer.agoralivestock.com.au/marketplace"
MLA_STATISTICS_URL = "https://www.mla.com.au/prices-markets/statistics/australian-goat-oth/"
OUTPUT_FILE = Path(__file__).with_name("goats.xml")


def fetch_bourke_grid():
    response = requests.get(
        AGORA_URL,
        timeout=30,
        headers={"User-Agent": "wagga-feed/1.0"},
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)

    # Agora currently publishes the Thomas Foods International Bourke goat
    # processor grid on its public marketplace. We deliberately target the
    # Bourke grid rather than the generic MLA OTH benchmark, because the
    # Dakboard block is intended to show the price relevant to the Broken Hill
    # depot / Bourke processor pathway.
    matches = []
    pattern = re.compile(
        r"Bourke\s+Goat\s+Grid\s+(\d+)\s*\(([^)]*)\).*?\$(\d+(?:\.\d+)?)\s*/kg\s*HSCW",
        re.I,
    )
    for match in pattern.finditer(text):
        grid_number = int(match.group(1))
        date_text = match.group(2).strip()
        price = float(match.group(3))
        matches.append((grid_number, date_text, price))

    if not matches:
        # The rendered page can place the price before the listing title.
        # Look for each Bourke Goat Grid mention and inspect a nearby window.
        fallback = re.compile(r"Bourke\s+Goat\s+Grid\s+(\d+)\s*\(([^)]*)\)", re.I)
        for match in fallback.finditer(text):
            window = text[max(0, match.start() - 700): min(len(text), match.end() + 700)]
            price_match = re.search(r"\$(\d+(?:\.\d+)?)\s*/kg\s*HSCW", window, re.I)
            if price_match:
                matches.append((int(match.group(1)), match.group(2).strip(), float(price_match.group(1))))

    if not matches:
        raise RuntimeError("Current Bourke goat processor grid not found on Agora marketplace")

    # Prefer the highest/current grid number. This avoids accidentally using
    # an older Bourke grid if Agora leaves historical listings in the page.
    grid_number, date_text, price = max(matches, key=lambda item: item[0])
    print(f"Agora Bourke goat grid {grid_number} ({date_text}): ${price:g}/kg HSCW")
    return price, grid_number, date_text


def update_xml(price, grid_number, date_text):
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    display_price = f"{price:g} c/kg cwt"
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
        price, grid_number, date_text = fetch_bourke_grid()
        update_xml(price, grid_number, date_text)
    except Exception as error:
        print("Goat update failed:", error)
        raise
