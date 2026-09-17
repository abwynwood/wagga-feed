import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

AGORA_URL = "https://portal.condabribeef.agoralivestock.com.au/"
OUTPUT_FILE = Path(__file__).with_name("goats.xml")
HISTORY_FILE = Path(__file__).with_name("goat_history.json")


def fetch_bourke_grid():
    # Agora is JavaScript-rendered. Read the rendered page text, then locate
    # the Bourke listing by its title and extract the price from that card.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(AGORA_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(10_000)
            text = re.sub(r"\s+", " ", page.locator("body").inner_text())
        finally:
            browser.close()

    # Current Agora card text is:
    #   Bourke Goat Grid 38 (16 Sep 26) ... $7.30 /kg HSCW
    # Allow optional spaces around the slash and tolerate intervening card
    # text, while requiring the price to belong to a Bourke Goat Grid card.
    title_pattern = re.compile(
        r"Bourke\s+Goat\s+Grid\s+(\d+)\s*\(([^)]*)\)", re.I
    )
    price_pattern = re.compile(
        r"\$\s*(\d+(?:\.\d+)?)\s*/?\s*kg\s*HSCW", re.I
    )

    matches = []
    for title_match in title_pattern.finditer(text):
        grid_number = int(title_match.group(1))
        date_text = title_match.group(2).strip()

        # First try the text immediately following the title. The listing
        # price is normally within the same card and appears shortly after it.
        window = text[title_match.end():title_match.end() + 1200]
        price_match = price_pattern.search(window)

        # Also try a window immediately before the title for older/card-layout
        # variants where the price precedes the title.
        if not price_match:
            window = text[max(0, title_match.start() - 1200):title_match.start()]
            price_match = price_pattern.search(window)

        if price_match:
            matches.append(
                (grid_number, date_text, float(price_match.group(1)))
            )

    if not matches:
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
        json.dumps(history, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
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
