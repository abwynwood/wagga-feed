import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os

URL = "https://www.grainflow.com.au/grain-prices"

def fetch_hillston_apw1():
    response = requests.get(URL)
    soup = BeautifulSoup(response.text, "html.parser")

    # Find Hillston row
    hillston_row = soup.find("td", string=lambda x: x and "Hillston" in x)
    if not hillston_row:
        return None

    # Find APW1 cell
    apw1_cell = hillston_row.find_next("td", string=lambda x: x and "APW1" in x)
    if not apw1_cell:
        return None

    # The next <td> contains the price
    price_cell = apw1_cell.find_next("td")
    price = price_cell.get_text(strip=True)

    return price


def update_xml(price):
    xml_path = "hillston_apw1.xml"

    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Hillston APW1</title>
    <link>{URL}</link>
    <description>Latest Hillston APW1 Price</description>
    <language>en-au</language>

    <item>
      <title>Hillston APW1</title>
      <link>{URL}</link>
      <guid>hillston-apw1</guid>
      <pubDate>{datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
      <description><![CDATA[
        <p><strong>APW1:</strong> {price}</p>
      ]]></description>
    </item>

  </channel>
</rss>""")


if __name__ == "__main__":
    price = fetch_hillston_apw1()

    # ⭐ KEEP LAST KNOWN PRICE LOGIC ⭐
    if price in ["N/A", "Pending", None, ""]:
        print("No new Hillston APW1 data — keeping last known price.")
        exit(0)

    update_xml(price)
