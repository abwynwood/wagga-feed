import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os

URL = "https://www.mla.com.au/prices-markets/market-reports/cattle/wagga/"

def fetch_prices():
    response = requests.get(URL)
    soup = BeautifulSoup(response.text, "html.parser")

    # Find the table containing averages
    table = soup.find("table")
    if not table:
        return None, None

    rows = table.find_all("tr")

    processor_cow = None
    young_cattle = None

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        label = cells[0].get_text(strip=True).lower()
        value = cells[1].get_text(strip=True)

        # Processor Cow Average
        if "processor" in label and "cow" in label:
            processor_cow = value

        # Young Cattle Average (handles all MLA label variations)
        if any(term in label for term in ["young", "yearling", "yc", "vealer"]):
            young_cattle = value

    return processor_cow, young_cattle


def update_xml(processor_cow, young_cattle):
    xml_path = "wagga_cattle.xml"

    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Wagga Cattle Averages</title>
    <link>{URL}</link>
    <description>Processor Cow & Young Cattle Averages</description>
    <language>en-au</language>

    <item>
      <title>Wagga Cattle Averages</title>
      <link>{URL}</link>
      <guid>wagga-cattle-averages</guid>
      <pubDate>{datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
      <description><![CDATA[
        <p><strong>Processor Cow Average:</strong> {processor_cow}</p>
        <p><strong>Young Cattle Average:</strong> {young_cattle}</p>
      ]]></description>
    </item>

  </channel>
</rss>""")


if __name__ == "__main__":
    processor_cow, young_cattle = fetch_prices()

    # ⭐ KEEP LAST KNOWN PRICE LOGIC ⭐
    if processor_cow in ["N/A", "Pending", None, ""] or young_cattle in ["N/A", "Pending", None, ""]:
        print("No new cattle data — keeping last known prices.")
        exit(0)

    update_xml(processor_cow, young_cattle)
