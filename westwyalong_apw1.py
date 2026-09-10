import re
import html
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

URL = "https://www.grainflow.com.au/daily-prices"
LOCATION = "West Wyalong"
GRADE = "APW1"
OUTPUT_FILE = "westwyalong_apw1.xml"


def fetch_price():
    response = requests.get(URL, timeout=30, headers={"User-Agent": "wagga-feed/1.0"})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # GrainFlow has changed its HTML layout over time. First try the
    # location heading + table, then fall back to scanning table rows.
    for heading in soup.find_all(["h2", "h3", "h4"]):
        if LOCATION.lower() in heading.get_text(" ", strip=True).lower():
            table = heading.find_next("table")
            if table:
                price = price_from_table(table)
                if price:
                    return price

    for table in soup.find_all("table"):
        text = table.get_text(" ", strip=True)
        if LOCATION.lower() in text.lower() and re.search(r"\b" + re.escape(GRADE) + r"\b", text, re.I):
            price = price_from_table(table)
            if price:
                return price

    # Last-resort text search: keep the location and grade close together
    # so another site's price cannot be selected.
    page_text = re.sub(r"\s+", " ", html.unescape(soup.get_text(" ", strip=True)))
    pattern = rf"{re.escape(LOCATION)}.{{0,1200}}?\b{re.escape(GRADE)}\b.{{0,250}}?(\$\s?[0-9,]+(?:\.\d+)?)"
    match = re.search(pattern, page_text, re.I)
    if match:
        return match.group(1).replace(" ", "")

    # Also allow the grade to appear before the location in the rendered text.
    pattern = rf"\b{re.escape(GRADE)}\b.{{0,1200}}?{re.escape(LOCATION)}.{{0,250}}?(\$\s?[0-9,]+(?:\.\d+)?)"
    match = re.search(pattern, page_text, re.I)
    if match:
        return match.group(1).replace(" ", "")

    return None


def price_from_table(table):
    for row in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
        row_text = " | ".join(cells)
        if not re.search(r"\b" + re.escape(GRADE) + r"\b", row_text, re.I):
            continue

        prices = re.findall(r"\$\s?[0-9,]+(?:\.\d+)?", row_text)
        if prices:
            return prices[-1].replace(" ", "")
    return None


def write_xml(price):
    now = datetime.now(timezone.utc)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{LOCATION} {GRADE}</title>
    <link>{URL}</link>
    <language>en-au</language>
    <item>
      <title>{LOCATION} {GRADE}</title>
      <link>{URL}</link>
      <guid>{LOCATION.lower().replace(" ", "-")}-{GRADE.lower()}</guid>
      <pubDate>{now.strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
      <description><![CDATA[
        <strong>{LOCATION} {GRADE}</strong><br>
        {price}
      ]]></description>
    </item>
  </channel>
</rss>
''')


if __name__ == "__main__":
    try:
        price = fetch_price()
    except Exception as error:
        print(f"GrainFlow fetch failed: {error}")
        price = None

    # Never replace a valid displayed price with N/A just because GrainFlow
    # temporarily changes layout or is unavailable.
    if price in [None, "", "N/A", "Pending"]:
        print(f"No new {LOCATION} {GRADE} data — keeping last known feed.")
    else:
        write_xml(price)
        print(f"Updated {LOCATION} {GRADE}: {price}")
