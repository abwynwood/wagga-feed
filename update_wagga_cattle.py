import requests
from bs4 import BeautifulSoup
from datetime import datetime

URL = "https://www.mla.com.au/prices-markets/market-reports/cattle/wagga/"

def fetch_wagga_averages():
    response = requests.get(URL)
    soup = BeautifulSoup(response.text, "html.parser")

    # Find the table containing category averages
    table = soup.find("table")
    if not table:
        return None, None

    processor_cows = None
    young_cattle = None

    # Loop through rows to find the categories we want
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        category = cells[0].get_text(strip=True).lower()
        price = cells[1].get_text(strip=True)

        if "processor" in category and "cow" in category:
            processor_cows = price

        if "young" in category and "cattle" in category:
            young_cattle = price

    return processor_cows, young_cattle


def update_xml(processor, young):
    xml_path = "wagga_cattle.xml"

    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Wagga Cattle Averages</title>
    <link>{URL}</link>
    <description>Weekly Wagga Processor Cow &amp; Young Cattle Averages</description>
    <language>en-au</language>

    <item>
      <title>Processor Cow Average</title>
      <link>{URL}</link>
      <guid>wagga-processor-cow</guid>
      <pubDate>{datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
      <description><![CDATA[
        <p><strong>Average Price:</strong> {processor}</p>
      ]]></description>
    </item>

    <item>
      <title>Young Cattle Average</title>
      <link>{URL}</link>
      <guid>wagga-young-cattle</guid>
      <pubDate>{datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
      <description><![CDATA[
        <p><strong>Average Price:</strong> {young}</p>
      ]]></description>
    </item>

  </channel>
</rss>""")


if __name__ == "__main__":
    processor, young = fetch_wagga_averages()
    if processor and young:
        update_xml(processor, young)
