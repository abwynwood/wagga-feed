import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

CROPCONNECT_URL = "https://cropconnect.com.au/cc/market/bids"


def current_season():
    now = datetime.now()
    if now.month >= 10:
        start = now.year
        end = now.year + 1
    else:
        start = now.year - 1
        end = now.year
    return f"{start % 100:02d}/{end % 100:02d}"


def normalise(text):
    return re.sub(r"\s+", " ", text or "").strip()


def prices_from_text(text):
    return [float(x.replace(",", "")) for x in re.findall(r"\$\s*([0-9][0-9,]*(?:\.\d+)?)", text)]


def extract_rows(page):
    selectors = [
        "tr",
        '[role="row"]',
        ".ag-row",
        ".MuiDataGrid-row",
    ]
    rows = []
    seen = set()
    for selector in selectors:
        try:
            for text in page.locator(selector).all_inner_texts():
                text = normalise(text)
                if text and text not in seen:
                    seen.add(text)
                    rows.append(text)
        except Exception:
            pass
    return rows


def fetch_highest_bid(location, grade):
    season = current_season()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1200})
        try:
            page.goto(CROPCONNECT_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(7000)

            rows = extract_rows(page)
            if not rows:
                # Some SPA layouts do not expose table rows. Use the rendered
                # page text as a conservative fallback and keep the match local.
                body = normalise(page.locator("body").inner_text(timeout=10000))
                rows = [body]

            candidates = []
            location_re = re.compile(rf"\b{re.escape(location)}\b", re.I)
            grade_re = re.compile(rf"\b{re.escape(grade)}\b", re.I)
            season_re = re.compile(rf"\b{re.escape(season)}\b")

            for row in rows:
                if not location_re.search(row) or not grade_re.search(row):
                    continue
                # Do not mix seasons. If a season is shown in the row, it must
                # be the current season. If the page has no season label at all,
                # the marketplace page itself is treated as the current-season view.
                season_tokens = re.findall(r"\b\d{2}/\d{2}\b", row)
                if season_tokens and not season_re.search(row):
                    continue
                prices = prices_from_text(row)
                if prices:
                    candidates.extend(prices)

            if not candidates:
                return None, season
            return max(candidates), season
        finally:
            browser.close()


def write_xml(location, grade, output_file, price, season):
    now = datetime.now(timezone.utc)
    value = f"${price:,.0f}/t" if price is not None else "Unavailable"
    Path(output_file).write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{location} {grade}</title>
    <link>{CROPCONNECT_URL}</link>
    <language>en-au</language>
    <item>
      <title>{location} {grade}</title>
      <link>{CROPCONNECT_URL}</link>
      <guid>{location.lower().replace(" ", "-")}-{grade.lower()}</guid>
      <pubDate>{now.strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
      <description><![CDATA[
        <strong>{location} {grade}</strong><br>
        {value}<br>
        Season {season}
      ]]></description>
    </item>
  </channel>
</rss>
''',
        encoding="utf-8",
    )


def update(location, grade, output_file):
    try:
        price, season = fetch_highest_bid(location, grade)
    except (PlaywrightTimeoutError, Exception) as error:
        print(f"CropConnect fetch failed for {location} {grade}: {error}")
        price = None
        season = current_season()

    write_xml(location, grade, output_file, price, season)
    if price is None:
        print(f"{location} {grade}: Unavailable")
    else:
        print(f"{location} {grade}: ${price:,.0f}/t (highest CropConnect bid, season {season})")


if __name__ == "__main__":
    raise SystemExit("Import cropconnect_grain.update() from the individual feed scripts.")
