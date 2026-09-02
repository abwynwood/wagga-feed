import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os

# MLA Griffith sheep report (no Cloudflare)
URL = "https://www.mla.com.au/prices-markets/market-reports/sheep/griffith/"
XML_FILE = "griffith.xml"

def fetch_report():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    page = requests.get(URL, headers=headers)
    soup = BeautifulSoup(page.content, "html.parser")

    # MLA uses the same structure for sheep reports as cattle
    report_section = soup.find("div", class_="market-report")

    # If MLA hasn't published a new report yet → skip update
    if not report_section:
        return None

    # Extract paragraphs and lists from the report
    paragraphs = [p.get_text(strip=True) for p in report_section.find_all("p")]
    lists = ["; ".join(li.get_text(strip=True) for li in ul.find_all("li"))
             for ul in report_section.find_all("ul")]

    # If MLA page is empty or placeholder → skip update
    if len(paragraphs) == 0:
        return None

    title = "Griffith Sheep Sale Report"
    summary = paragraphs[0] if paragraphs else None
    details = paragraphs[1] if len(paragraphs) > 1 else None
    extra = lists[0] if lists else None

    # If all fields are empty → skip update
    if not summary and not details and not extra:
        return None

    pubdate = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

    return title, summary, details, extra, pubdate


def update_xml(title, summary, details, extra, pubdate):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Griffith Sheep Sale Report</title>

    <!-- Stable MLA sheep reports index -->
    <link>https://www.mla.com.au/prices-markets/market-reports/sheep/</link>

    <description>Automatically updated Griffith sheep sale report (MLA source)</description>
    <language>en-au</language>

    <item>
      <title>{title}</title>
      <pubDate>{pubdate}</pubDate>
      <description><![CDATA[
        <strong>Summary:</strong> {summary}<br><br>
        <strong>Details:</strong> {details}<br><br>
        <strong>Extra:</strong> {extra}
      ]]></description>
    </item>

  </channel>
</rss>
"""
    with open(XML_FILE, "w", encoding="utf-8") as f:
        f.write(xml)


if __name__ == "__main__":
    result = fetch_report()

    if result is None:
        print("No new MLA Griffith sheep report — keeping existing griffith.xml")
    else:
        title, summary, details, extra, pubdate = result
        update_xml(title, summary, details, extra, pubdate)
        print("Updated griffith.xml with new MLA report")
