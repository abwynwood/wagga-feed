import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

REPORT_URL = "https://app.nlrsreports.mla.com.au/statistics/nlrs-goat-oth/"
MLA_STATISTICS_URL = "https://www.mla.com.au/prices-markets/statistics/australian-goat-oth/"
OUTPUT_FILE = Path(__file__).with_name("goats.xml")


WEIGHT_PATTERN = re.compile(
    r"16\s*\.?1?\s*(?:kg\s*)?(?:-|–|—|to)\s*20\s*\.?0?\s*kg?",
    re.I,
)


def normalise(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def is_target_row(row):
    text = normalise(" ".join(row))
    compact = text.replace(" ", "")
    return bool(
        WEIGHT_PATTERN.search(text)
        or "16.1-20" in compact
        or "16.1–20" in text
        or "16-20kg" in compact
        or "16–20kg" in text
    )


def numeric_values(row):
    values = []
    for index, cell in enumerate(row):
        value = str(cell).strip().replace(",", "")
        value = value.replace("¢", "").replace("c/kg", "").replace("c/kg cwt", "")
        match = re.fullmatch(r"(?:\$\s*)?(\d+(?:\.\d+)?)", value)
        if not match:
            continue
        number = float(match.group(1))
        if 0 < number < 2000:
            # If the export expresses the price in dollars/kg, convert to cents/kg.
            if number < 20:
                number *= 100
            values.append((index, number))
    return values


def parse_price(row):
    values = numeric_values(row)
    if not values:
        return None

    # Prefer a column explicitly labelled as the current/this-week price.
    labels = [normalise(cell) for cell in row]
    preferred = []
    for index, number in values:
        nearby = " ".join(labels[max(0, index - 2): min(len(labels), index + 3)])
        if any(term in nearby for term in ("this week", "current", "latest", "price", "average", "week")):
            preferred.append(number)
    if preferred:
        return round(preferred[0], 1)

    # Otherwise the first plausible price in the matching weight row is the
    # current value in MLA's export layout.
    return round(values[0][1], 1)


def extract_csv_price(content):
    text = content.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))

    for row in rows:
        if is_target_row(row):
            price = parse_price(row)
            if price is not None:
                print("MLA goat OTH target row:", row)
                print(f"MLA goat OTH parsed 16–20kg price: {price:g} c/kg cwt")
                return price

    # Some MLA exports split the weight label across adjacent cells. Try joining
    # every row with a visible separator as a second pass.
    for row in rows:
        joined = " | ".join(str(cell) for cell in row)
        if re.search(r"16\s*\.?(?:1)?\s*(?:kg\s*)?(?:-|–|—|to)\s*20", joined, re.I):
            price = parse_price(row)
            if price is not None:
                print("MLA goat OTH fallback row:", row)
                return price

    sample = [row for row in rows if any(ch.isdigit() for ch in " ".join(row))][:12]
    print("MLA goat OTH CSV rows inspected; no 16–20kg row matched:")
    for row in sample:
        print(row)
    raise RuntimeError("MLA goat OTH 16–20kg row/current price not found in export")


def fetch_goat_price():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
        try:
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
        print("Goat update failed:", error)
        raise
