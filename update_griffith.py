import requests
from bs4 import BeautifulSoup
from datetime import datetime

URL = "https://agoralivestock.com.au/griffith-sheep-sale-report"
XML_FILE = "griffith.xml"

def fetch_report():
    page = requests.get(URL)
    soup = BeautifulSoup(page.content, "html.parser")

    # Main content container
    content = soup.find("div", class_="report-content")

    if not content:
        return (
            "Date unavailable",
            "Yarding unavailable",
            "Trend information unavailable",
            "Top prices unavailable",
            "Commentary unavailable",
            datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
        )

    # Extract fields safely
    def safe_text(selector):
        tag = content.find(selector)
        return tag.get_text(strip=True) if tag else "Unavailable"

    date = safe_text("h2")
    yarding = safe_text("div")
    trends = safe_text("section")
    top_prices = safe_text("ul")
    commentary = safe_text("p")

    pubdate = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

    return date, yarding, trends, top_prices, commentary, pubdate


def update_xml(date, yarding, trends, top_prices, commentary, pubdate):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Griffith Sheep Sale Report</title>
    <link>{URL}</link>
    <description>Automatically updated Griffith sheep sale report</description>
    <language>en-au</language>

    <item>
      <title>Griffith Sheep Sale – {date}</title>
      <pubDate>{pubdate}</pubDate>
      <description><![CDATA[
        <strong>Yarding:</strong> {yarding}<br><br>
        <strong>Trends:</strong> {trends}<br><br>
        <strong>Top Prices:</strong> {top_prices}<br><br>
        <strong>Commentary:</strong> {commentary}
      ]]></description>
    </item>

  </channel>
</rss>
"""
    with open(XML_FILE, "w", encoding="utf-8") as f:
        f.write(xml)


if __name__ == "__main__":
    date, yarding, trends, top_prices, commentary, pubdate = fetch_report()
    update_xml(date, yarding, trends, top_prices, commentary, pubdate)
