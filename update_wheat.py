import requests
from bs4 import BeautifulSoup
from datetime import datetime

URL = "https://www.dpi.nsw.gov.au/agriculture/grains/weekly-grain-report"

def fetch_wheat_price():
    response = requests.get(URL)
    soup = BeautifulSoup(response.text, "html.parser")

    # Find the APW1 row
    apw1_row = soup.find("td", string=lambda x: x and "APW1" in x)
    if not apw1_row:
        return None

    # NSW average price is usually the next <td>
    price_cell = apw1_row.find_next("td")
    price = price_cell.get_text(strip=True)

    return price

def update_xml(price):
    xml_path = "wheat.xml"

    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>NSW Wheat APW1 Price</title>
    <link>https://www.dpi.nsw.gov.au/agriculture/grains</link>
    <description>Latest NSW APW1 wheat average price</description>
    <language>en-au</language>

    <item>
      <title>NSW Wheat APW1 Price</title>
      <link>https://www.dpi.nsw.gov.au/agriculture/grains</link>
      <guid>wheat-apw1-price</guid>
      <pubDate>{datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
      <description><![CDATA[
        <p><strong>Price:</strong> {price}</p>
        <p><strong>Details:</strong> NSW APW1 wheat average price from DPI Weekly Grain Report.</p>
      ]]></description>
    </item>

  </channel>
</rss>""")

if __name__ == "__main__":
    price = fetch_wheat_price()
    if price:
        update_xml(price)
