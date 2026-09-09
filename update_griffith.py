import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os

URL = "https://www.lls.nsw.gov.au/regions/riverina/livestock-markets/griffith-saleyards"

def fetch_sheep_report():
    response = requests.get(URL)
    soup = BeautifulSoup(response.text, "html.parser")

    # Find the Griffith sheep report text
    report_section = soup.find("div", class_="rich-text")
    if not report_section:
        return None

    text = report_section.get_text(strip=True)
    if not text:
        return None

    return text

def update_xml(report):
    xml_path = "griffith.xml"

    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Griffith Sheep Report</title>
    <link>{URL}</link>
    <description>Latest Griffith Sheep Market Report</description>
    <language>en-au</language>

    <item>
      <title>Griffith Sheep Report</title>
      <link>{URL}</link>
      <guid>griffith-sheep-report</guid>
      <pubDate>{datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
      <description><![CDATA[
        {report}
      ]]></description>
    </item>

  </channel>
</rss>""")

if __name__ == "__main__":
    report = fetch_sheep_report()

    # ⭐ KEEP LAST KNOWN PRICE LOGIC ⭐
    if report in ["N/A", "Pending", None, ""]:
        print("No new sheep report — keeping last known data.")
        exit(0)

    update_xml(report)
