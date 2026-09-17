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
            for _ in range(3):
                page.mouse.wheel(0, 1800)
                page.wait_for_timeout(2_000)

            blocks = []
            for frame in page.frames:
                try:
                    soup = BeautifulSoup(frame.content(), "html.parser")
                    # Preserve DOM blocks so a price can only be paired with
                    # the Bourke Goat Grid listing it belongs to.
                    for node in soup.find_all(["article", "li", "tr", "div"]):
                        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
                        if re.search(r"Bourke\s+Goat\s+Grid", text, re.I):
                            blocks.append(text)
                except Exception:
                    continue
        finally:
            browser.close()

    title_pattern = re.compile(
        r"Bourke\s+Goat\s+Grid\s+(\d+[A-Za-z]?)\s*\(([^)]*)\)", re.I
    )
    price_pattern = re.compile(
        r"\$\s*(\d+(?:\.\d+)?)\s*/?\s*kg\s*HSCW", re.I
    )

    matches = []
    seen = set()
    for block in blocks:
        title_match = title_pattern.search(block)
        price_match = price_pattern.search(block)
        if not title_match or not price_match:
            continue
        grid_text = title_match.group(1).strip()
        date_text = title_match.group(2).strip()
        price_dollars = float(price_match.group(1))
        key = (grid_text, date_text, price_dollars)
        if key not in seen:
            seen.add(key)
            matches.append(key)

    if not matches:
        raise RuntimeError("Current Bourke goat processor grid not found on Agora portal")

    def date_sort_key(item):
        try:
            return datetime.strptime(item[1], "%d %b %y")
        except ValueError:
            return datetime.min

    # Select the newest Bourke Goat Grid listing, regardless of its grid number.
    grid_text, date_text, price_dollars = max(matches, key=date_sort_key)
    price_cents = round(price_dollars * 100, 1)
    print(f"Agora Bourke goat grid {grid_text} ({date_text}): ${price_dollars:g}/kg HSCW = {price_cents:g} c/kg cwt")
    return price_cents, grid_text, date_text


def load_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    history[:] = [entry for entry in history if entry.get("timestamp", "") >= (now - timedelta(days=30)).isoformat()]

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
        <p>(15kg carcass: ${carcass_value_15kg:.2f})</p>
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
