import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

AGORA_URL = "https://portal.condabribeef.agoralivestock.com.au/"
OUTPUT_FILE = Path(__file__).with_name("goats.xml")
HISTORY_FILE = Path(__file__).with_name("goat_history.json")


def fetch_bourke_grid():
    # Agora is a JavaScript marketplace. GitHub's browser needs to inspect the
    # rendered DOM/frames rather than relying only on body.inner_text().
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                viewport={"width": 1440, "height": 1200},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
                ),
            )
            page.goto(AGORA_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(15_000)

            # Give the marketplace a chance to load listings which are fetched
            # after the initial page render.
            for _ in range(3):
                page.mouse.wheel(0, 1800)
                page.wait_for_timeout(2_000)

            texts = []
            for frame in page.frames:
                try:
                    html = frame.content()
                    soup = BeautifulSoup(html, "html.parser")
                    texts.append(soup.get_text(" ", strip=True))
                    # Also inspect script text because some React/Next-style
                    # apps retain listing data in embedded JSON.
                    texts.extend(
                        script.get_text(" ", strip=True)
                        for script in soup.find_all("script")
                    )
                except Exception:
                    continue
        finally:
            browser.close()

    combined = re.sub(r"\s+", " ", " ".join(texts))

    title_pattern = re.compile(
        r"Bourke\s+Goat\s+Grid\s+(\d+)\s*\(([^)]*)\)", re.I
    )
    price_pattern = re.compile(
        r"\$\s*(\d+(?:\.\d+)?)\s*/?\s*kg\s*HSCW", re.I
    )

    matches = []
    for title_match in title_pattern.finditer(combined):
        grid_number = int(title_match.group(1))
        date_text = title_match.group(2).strip()

        # The title and price are in the same listing card, but HTML structure
        # can vary. Search a generous local window in both directions.
        windows = [
            combined[title_match.end():title_match.end() + 2500],
            combined[max(0, title_match.start() - 2500):title_match.start()],
        ]
        price_match = next(
            (price_pattern.search(window) for window in windows if price_pattern.search(window)),
            None,
        )

        if price_match:
            matches.append((grid_number, date_text, float(price_match.group(1))))

    if not matches:
        # Leave a useful diagnostic in the Actions log without dumping the
        # whole page. This makes future Agora layout changes much easier to fix.
        bourke_positions = [m.start() for m in re.finditer("Bourke", combined, re.I)]
        print(f"Agora diagnostic: found {len(bourke_positions)} occurrences of 'Bourke' in rendered content")
        for position in bourke_positions[:5]:
            print(combined[max(0, position - 250):position + 700])
        raise RuntimeError("Current Bourke goat processor grid not found on Agora portal")

    grid_number, date_text, price_dollars = max(matches, key=lambda item: item[0])
    price_cents = round(price_dollars * 100, 1)
    print(
        f"Agora Bourke goat grid {grid_number} ({date_text}): "
        f"${price_dollars:g}/kg HSCW = {price_cents:g} c/kg cwt"
    )
    return price_cents, grid_number, date_text


def load_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_history(history):
    HISTORY_FILE.write_text(
        json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def trend_for(value, history):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)
    previous = None
    for entry in reversed(history):
        try:
            timestamp = datetime.fromisoformat(entry["timestamp"])
            price = float(entry["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if timestamp <= cutoff:
            previous = price
            break

    history.append({"timestamp": now.isoformat(), "price": value})
    history[:] = [
        entry for entry in history
        if entry.get("timestamp", "") >= (now - timedelta(days=30)).isoformat()
    ]

    if previous is None:
        return ""
    change = round(value - previous, 1)
    if abs(change) < 0.5:
        return "→ Steady from 7 days ago"
    if change > 0:
        return f"↑ Firming +{change:g} c/kg cwt from 7 days ago"
    return f"↓ Softer {change:g} c/kg cwt from 7 days ago"


def update_xml(price_cents, grid_number, date_text, trend):
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    price_dollars = price_cents / 100
    carcass_value_15kg = price_dollars * 15
    trend_line = f"<p>{trend}</p>" if trend else ""

    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Bourke Goat Processor Grid</title>
    <link>{AGORA_URL}</link>
    <description>Current Thomas Foods International Bourke goat processor grid published by Agora Livestock</description>
    <language>en-au</language>
    <item>
      <title>Bourke Goat Grid {grid_number} ({date_text})</title>
      <link>{AGORA_URL}</link>
      <guid>bourke-goat-grid</guid>
      <pubDate>{now}</pubDate>
      <description><![CDATA[
        <p><strong>Price:</strong> {price_cents:g} c/kg cwt</p>
        <p><strong>15kg carcass:</strong> ${carcass_value_15kg:.2f}</p>
        <p><strong>Processor:</strong> Thomas Foods International, Bourke</p>
        {trend_line}
      ]]></description>
    </item>
  </channel>
</rss>'''
    OUTPUT_FILE.write_text(xml, encoding="utf-8")


if __name__ == "__main__":
    try:
        price_cents, grid_number, date_text = fetch_bourke_grid()
        history = load_history()
        trend = trend_for(price_cents, history)
        save_history(history)
        update_xml(price_cents, grid_number, date_text, trend)
    except Exception as error:
        print("Goat update failed:", error)
        raise
