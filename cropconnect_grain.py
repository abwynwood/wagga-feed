import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

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


def candidate_texts(page):
    """Collect rendered text from the main page and any iframes."""
    texts = []
    seen = set()
    for frame in page.frames:
        try:
            text = normalise(frame.locator("body").inner_text(timeout=5000))
            if text and text not in seen:
                seen.add(text)
                texts.append(text)
        except Exception:
            pass
    return texts


def fetch_highest_bid(location, grade):
    season = current_season()
    network_json = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1200})
        page = context.new_page()

        def capture_response(response):
            # CropConnect is a SPA, so the useful bid data may arrive through
            # an XHR/fetch rather than being present in the initial HTML.
            ctype = (response.headers.get("content-type") or "").lower()
            if "json" not in ctype:
                return
            try:
                body = response.text()
                if body and len(body) < 2_000_000:
                    network_json.append((response.url, body))
            except Exception:
                pass

        page.on("response", capture_response)

        try:
            page.goto(CROPCONNECT_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(12000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            # Give SPA/iframe content another moment to render.
            page.wait_for_timeout(3000)
            texts = candidate_texts(page)

            location_re = re.compile(rf"\b{re.escape(location)}\b", re.I)
            grade_re = re.compile(rf"\b{re.escape(grade)}\b", re.I)
            season_re = re.compile(rf"\b{re.escape(season)}\b")
            candidates = []

            # First use rendered text. This is the safest source because it is
            # exactly what the CropConnect marketplace presents to the user.
            for text in texts:
                for chunk in re.split(r"\n|(?<=\$[0-9,]+)", text):
                    row = normalise(chunk)
                    if not location_re.search(row) or not grade_re.search(row):
                        continue
                    season_tokens = re.findall(r"\b\d{2}/\d{2}\b", row)
                    if season_tokens and not season_re.search(row):
                        continue
                    prices = prices_from_text(row)
                    if prices:
                        candidates.extend(prices)

            # If the UI doesn't expose rows cleanly, inspect JSON returned by
            # the SPA. Only accept JSON that actually contains the requested
            # location and grade, and only prices from the current season when
            # a season field is present.
            if not candidates:
                for url, body in network_json:
                    if not location_re.search(body) or not grade_re.search(body):
                        continue
                    try:
                        data = json.loads(body)
                    except Exception:
                        continue
                    blob = json.dumps(data, ensure_ascii=False)
                    if not location_re.search(blob) or not grade_re.search(blob):
                        continue
                    if re.findall(r"\b\d{2}/\d{2}\b", blob) and not season_re.search(blob):
                        continue
                    # Price keys commonly used by marketplace APIs.
                    for match in re.finditer(
                        r'"(?:price|bidPrice|cashPrice|amount|value)"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
                        blob,
                        re.I,
                    ):
                        try:
                            candidates.append(float(match.group(1)))
                        except ValueError:
                            pass

            if not candidates:
                # Print safe diagnostics into Actions logs so the next failed
                # attempt tells us what CropConnect actually returned.
                print(f"CropConnect diagnostic {location} {grade}: frames={len(page.frames)} json_responses={len(network_json)}")
                for frame in page.frames:
                    print(f"frame: {frame.url}")
                for url, body in network_json[:20]:
                    print(f"json: {url} :: {normalise(body)[:500]}")
                for text in texts[:5]:
                    print(f"page-text: {text[:1000]}")
                return None, season

            return max(candidates), season
        finally:
            context.close()
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
    except Exception as error:
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
