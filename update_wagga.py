import requests
from bs4 import BeautifulSoup
import datetime

URL = "https://www.beefcentral.com/markets/wagga/"

def fetch_latest_report():
    page = requests.get(URL)
    soup = BeautifulSoup(page.content, "html.parser")

    # Find the first Wagga report article
    article = soup.find("div", class_="post")
    title = article.find("h2").get_text(strip=True)
    link = article.find("a")["href"]

    # Extract summary text (first paragraph)
    summary = article.find("p").get_text(strip=True)

    # Fake yarding extraction (Beef Central varies formatting)
    # You can refine this later
    yarding = "Yarding data unavailable"

    return title, link, summary, yarding

def build_rss(title, link, summary, yarding):
    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Wagga Livestock Market Reports – Beef Central</title>
    <link>{URL}</link>
    <description>Automatically updated feed of Wagga saleyard reports</description>
    <language>en-au</language>

    <item>
      <title>{title}</title>
      <link>{link}</link>
      <description>
        {summary}
      </description>
    </item>

  </channel>
</rss>
"""
    return rss

if __name__ == "__main__":
    title, link, summary, yarding = fetch_latest_report()
    rss = build_rss(title, link, summary, yarding)

    with open("wagga.xml", "w", encoding="utf-8") as f:
        f.write(rss)
