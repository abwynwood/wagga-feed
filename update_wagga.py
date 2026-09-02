import requests
from bs4 import BeautifulSoup

URL = "https://www.beefcentral.com/markets/wagga/"

def fetch_latest_report():
    page = requests.get(URL)
    soup = BeautifulSoup(page.content, "html.parser")

    # Beef Central now uses <div class="post"> inside <div class="post-list">
    article = soup.find("div", class_="post")

    if not article:
        return ("Wagga market report unavailable",
                URL,
                "No report found on Beef Central.",
                "Yarding unavailable")

    # Title is now inside <h3> not <h2>
    title_tag = article.find(["h2", "h3"])
    title = title_tag.get_text(strip=True) if title_tag else "Wagga market report"

    # Link is inside the first <a>
    link_tag = article.find("a")
    link = link_tag["href"] if link_tag else URL

    # Summary is inside the first <p>
    summary_tag = article.find("p")
    summary = summary_tag.get_text(strip=True) if summary_tag else "Summary unavailable."

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
      <description>{summary}</description>
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
