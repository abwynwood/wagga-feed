import requests
from bs4 import BeautifulSoup
from datetime import datetime

URL = "https://agoralivestock.com.au/griffith-sheep-sale-report"
XML_FILE = "griffith.xml"

def fetch_report():
    response = requests.get(URL, timeout=10)
    soup = BeautifulSoup(response.text, "html.parser")

    # Extract date
    date_tag = soup.find("time")
    date_text = date_tag.get_text(strip=True) if date_tag else "Unknown date"

    # Extract yarding
    yarding_tag = soup.find(string=lambda t: "yarding" in t.lower())
    yarding = yarding_tag.strip() if yarding_tag else "Yarding not found"

    # Extract price trends
    trends_tag = soup.find(string=lambda t: "dearer" in t.lower() or "easier" in t.lower() or "firm" in t.lower())
    trends = trends_tag.strip() if trends_tag else "Price trends not found"

    # Extract top prices
    top_tag = soup.find(string=lambda t: "topped" in t.lower() or "sold to" in t.lower())
    top_prices = top_tag.strip() if top_tag else "Top prices not found"

    # Extract commentary (first paragraph)
    p = soup.find("p")
    commentary = p.get_text(strip=True) if p else "Commentary not found"

    # PubDate format
    pubdate = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")

    return date_text, yarding, trends, top_prices, commentary, pubdate


def update_xml(date, yarding, trends, top_prices, commentary, pubdate):
    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Griffith Sheep Sale Report</title>
    <link>{URL}</link>
    <description>Latest Griffith sheep saleyard market report</description>

    <item>
      <title>Griffith Sheep Sale – {date}</title>
      <description>
        Total yarding: {yarding}
        Price trends: {trends}
        Top prices: {top_prices}
        Commentary: {commentary}
      </description>
      <link>{URL}</link>
      <pubDate>{pubdate}</pubDate>
    </item>

  </channel>
</rss>
"""
    with open(XML_FILE, "w", encoding="utf-8") as f:
        f.write(xml_content)


if __name__ == "__main__":
    date, yarding, trends, top_prices, commentary, pubdate = fetch_report()
    update_xml(date, yarding, trends, top_prices, commentary, pubdate)
