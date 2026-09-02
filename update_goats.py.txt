import requests
from bs4 import BeautifulSoup
from datetime import datetime

URL = "https://www.mla.com.au/prices-markets/market-reports/goat/over-the-hooks-goat-indicators/"

def fetch_goat_price():
    response = requests.get(URL)
    soup = BeautifulSoup(response.text, "html.parser")

    # Find the NSW OTH Goat row
    # MLA tables usually have NSW in the first column
    nsw_row = soup.find("td", string=lambda x: x and "NSW" in x)
    if not nsw_row:
        return None

    # Find the cell containing "Goat" or "OTH Goat"
    indicator_cell = nsw_row.find_next("td")
    if not indicator_cell or ("Goat" not in indicator_cell.get_text()):
        return None

    # The next <td> contains the price (c/kg)
    price_cell = indicator_cell.find_next("td")
    price = price_cell.get_text(strip=True)

    return price

def update_xml(price):
    xml_path = "goats.xml"

    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>NSW Goat OTH Price</title>
    <link>https://www.mla.com.au/prices-markets/market-reports/goat/over-the-hooks-goat-indicators/</link>
    <description>Latest NSW Over-the-Hooks Goat Price</description>
    <language>en-au</language>

    <item>
      <title>NSW Goat OTH Price</title>
      <link>https://www.mla.com.au/prices-markets/market-reports/goat/over-the-hooks-goat-indicators/</link>
      <guid>nsw-goat-oth-price</guid>
      <pubDate>{datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
      <description><![CDATA[
        <p><strong>Price:</strong> {price}</p>
        <p><strong>Details:</strong> NSW Over-the-Hooks Goat Indicator from MLA Weekly Report.</p>
      ]]></description>
    </item>

  </channel>
</rss>""")

if __name__ == "__main__":
    price = fetch_goat_price()
    if price:
        update_xml(price)
