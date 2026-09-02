import requests
from bs4 import BeautifulSoup
from datetime import datetime

URL = "https://www.beefcentral.com/markets/wagga/"
XML_FILE = "wagga.xml"

def fetch_report():
    # Full browser headers so Cloudflare allows GitHub Actions
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    page = requests.get(URL, headers=headers)
    soup = BeautifulSoup(page.content, "html.parser")

    # Collect text blocks from the page
    headers_text = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])]
    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
    lists = ["; ".join(li.get_text(strip=True) for li in ul.find_all("li")) for ul in soup.find_all("ul")]

    # Assign best guesses based on page structure
    title = headers_text[0] if headers_text else "Wagga Cattle Market Report"
    summary = paragraphs[0] if paragraphs else "Summary unavailable"
    details = paragraphs[1] if len(paragraphs) > 1 else "Details unavailable"
    extra = lists[0] if lists else "Additional info unavailable"

    pubdate = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

    return title, summary, details, extra, pubdate


def update_xml(title, summary, details, extra, pubdate):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Wagga Cattle Market Report</title>
    <link>{URL}</link>
    <description>Automatically updated Wagga cattle market report</description>
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
    title, summary, details, extra, pubdate = fetch_report()
    update_xml(title, summary, details, extra, pubdate)
