import requests
from bs4 import BeautifulSoup
from datetime import datetime

URL = "https://agoralivestock.com.au/griffith-sheep-sale-report"
XML_FILE = "griffith.xml"

def fetch_report():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    page = requests.get(URL, headers=headers)
    soup = BeautifulSoup(page.content, "html.parser")

    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
    headers_text = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])]
    lists = ["; ".join(li.get_text(strip=True) for li in ul.find_all("li")) for ul in soup.find_all("ul")]

    date = headers_text[0] if headers_text else "Date unavailable"
    yarding = paragraphs[0] if paragraphs else "Yarding unavailable"
    trends = paragraphs[1] if len(paragraphs) > 1 else "Trends unavailable"
    commentary = paragraphs[-1] if paragraphs else "Commentary unavailable"
    top_prices = lists[0] if lists else "Top prices unavailable"

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
