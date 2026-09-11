import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

REPORT_URL = "https://app.nlrsreports.mla.com.au/statistics/nlrs-goat-oth/"
MLA_STATISTICS_URL = "https://www.mla.com.au/prices-markets/statistics/australian-goat-oth/"
OUTPUT_FILE = Path(__file__).with_name("goats.xml")


def normalise(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def is_target_row(row):
    text = normalise(" ".join(row))
    compact = text.replace(" ", "")
    return (
        ("16.1-20" in compact or "16-20" in compact or "16.1–20" in text or "16–20" in text)
        and ("kg" in text or "cwt" in text)
        and any(term in text for term in ("goat", "oth", "over the hooks", "over-the-hooks"))
    )


def parse_price(row):
    preferred_indexes = []
    for index, cell in enumerate(row):
        label = normalise(cell)
        if any(term in label for term in ("this week", "current", "tw", "price", "average")):
            preferred_indexes.append(index)

    candidates = []
    for index in preferred_indexes + list(range(len(row))):
        if index >= len(row):
            continue
        value = str(row[index]).replace(",", "")
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", value)
        if match:
            number = float(match.group(1))
            if 50 < number < 2000:
                candidates.append(number)

    return candidates[0] if candidates else None


def extract_csv_price(content):
    text = content.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    for row in rows:
        if is_target_row(row):
            price = parse_price(row)
            if price is not None:
                print("MLA goat OTH CSV row:", row)
                return round(price, 1)
    raise RuntimeError("MLA goat OTH 16.1–20kg row or current price not found in export")


def fetch_goat_price():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
        try:
            # Do not wait for networkidle: the MLA report keeps analytics/background
            # requests open indefinitely, which caused the previous 120-second timeout.
            page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=60000)

            button = page.get_by_role("button", name=re.compile(r"export data", re.I))
            if button.count() == 0:
                button = page.get_by_text(re.compile(r"export data", re.I))
            if button.count() == 0:
                raise RuntimeError("MLA Goat OTH Export Data button not found")

            button.first.wait_for(state="visible", timeout=30000)
            page.wait_for_timeout(5000)

            with page.expect_download(timeout=60000) as download_info:
                button.first.click()
            download = download_info.value
            content = Path(download.path()).read_bytes()
            filename = download.suggested_filename or "goat_oth_export.csv"
            print(f"Downloaded MLA Goat OTH export: {filename}")

            if filename.lower().endswith((".csv", ".txt")) or b"," in content[:2000]:
                return extract_csv_price(content)
            raise RuntimeError(f"Unsupported MLA export format: {filename}")
        finally:
            browser.close()


def update_xml(price):
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    display_price = f"{price:g} c/kg cwt"
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>NSW Goat OTH Price</title>
    <link>{MLA_STATISTICS_URL}</link>
    <description>Latest MLA Eastern States goat Over-the-Hooks benchmark</description>
    <language>en-au</language>
    <item>
      <title>NSW Goat OTH — 16–20kg cwt</title>
      <link>{MLA_STATISTICS_URL}</link>
      <guid>nsw-goat-oth-16-20kg</guid>
      <pubDate>{now}</pubDate>
      <description><![CDATA[
        <p><strong>Price:</strong> {display_price}</p>
        <p><strong>Benchmark:</strong> Eastern States 16–20kg cwt</p>
        <p><strong>Source:</strong> Meat &amp; Livestock Australia (MLA)</p>
      ]]></description>
    </item>
  </channel>
</rss>'''
    OUTPUT_FILE.write_text(xml, encoding="utf-8")


if __name__ == "__main__":
    try:
        price = fetch_goat_price()
        print(f"MLA goat OTH: {price:g} c/kg cwt")
        update_xml(price)
    except Exception as error:
        if OUTPUT_FILE.exists():
            print("Goat update failed; retaining last known price:", error)
        else:
            raise
