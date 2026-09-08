import requests
from bs4 import BeautifulSoup

URL = "https://www.grainflow.com.au/daily-prices"
OUTPUT_FILE = "hillston_bar1.xml"

def fetch_hillston_bar1():
    try:
        response = requests.get(URL, timeout=20)
        response.raise_for_status()
    except Exception:
        return "N/A"

    soup = BeautifulSoup(response.text, "html.parser")

    hillston_section = soup.find("h3", string="Hillston")
    if not hillston_section:
        return "N/A"

    table = hillston_section.find_next("table")
    if not table:
        return "N/A"

    rows = table.find_all("tr")

    bar1_price = "N/A"

    for row in rows:
        cells = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cells) >= 5 and cells[1] == "BAR1":
            bar1_price = cells[4].replace("$", "")
            break

    return bar1_price


def write_xml(price):
    xml_content = f"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Hillston BAR1</title>
    <item>
      <title>Hillston BAR1</title>
      <description>{price}</description>
    </item>
  </channel>
</rss>
"""
    with open(OUTPUT_FILE, "w") as f:
        f.write(xml_content)


if __name__ == "__main__":
    price = fetch_hillston_bar1()
    write_xml(price)
