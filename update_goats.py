import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

AGORA_URL = "https://portal.condabribeef.agoralivestock.com.au/"
OUTPUT_FILE = Path(__file__).with_name("goats.xml")
HISTORY_FILE = Path(__file__).with_name("goat_history.json")


def fetch_bourke_grid():
    title_pattern = re.compile(
        r'"title"\s*:\s*"Bourke\s+Goat\s+Grid\s+(\d+[A-Za-z]?)\s*\(([^)]*)\)"',
        re.I,
    )
    prices_pattern = re.compile(
        r'"prices"\s*:\s*\{\s*"HSCW"\s*:\s*\{\s*"min"\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*"max"\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*\}',
        re.I,
    )
    visible_title_pattern = re.compile(
        r'Bourke\s+Goat\s+Grid\s+(\d+[A-Za-z]?)\s*\(\s*(\d{1,2}\s+[A-Za-z]{3}\s+\d{2})\s*\)',
        re.I,
    )
    visible_price_pattern = re.compile(
        r'\$\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*kg\s*HSCW',
        re.I,
    )

    matches = []
    seen = set()

    def collect(documents):
        for document in documents:
            for title_match in title_pattern.finditer(document):
                next_title = title_pattern.search(document, title_match.end())
                section = document[
                    title_match.end():
                    next_title.start() if next_title else title_match.end() + 15000
                ]
                price_match = prices_pattern.search(section)
                if not price_match:
                    continue
                minimum = float(price_match.group(1))
                maximum = float(price_match.group(2))
                if minimum != maximum:
                    continue
                key = (
                    title_match.group(1).strip(),
                    title_match.group(2).strip(),
                    minimum,
                )
                if key not in seen:
                    seen.add(key)
                    matches.append(key)

            # Fallback: use the rendered page text if Agora's internal JSON
            # is unavailable on a particular run.
            for title_match in visible_title_pattern.finditer(document):
                section = document[title_match.start():title_match.start() + 2500]
                price_match = visible_price_pattern.search(section)
                if not price_match:
                    continue
                price = float(price_match.group(1))
                key = (
                    title_match.group(1).strip(),
                    title_match.group(2).strip(),
                    price,
                )
                if key not in seen:
                    seen.add(key)
                    matches.append(key)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                viewport={"width": 1440, "height": 1400},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
                ),
            )

            # Agora is client-rendered and occasionally doesn't expose the
            # marketplace listing on the first load. Retry the actual page.
            for attempt in range(4):
                documents = []
                try:
                    if attempt == 0:
                        page.goto(
                            AGORA_URL,
                            wait_until="domcontentloaded",
                            timeout=60_000,
                        )
                    else:
                        page.reload(
                            wait_until="domcontentloaded",
                            timeout=60_000,
                        )
                except Exception as error:
                    print(f"Agora load attempt {attempt + 1} failed: {error}")
                    continue

                page.wait_for_timeout(15_000 + attempt * 5_000)

                for _ in range(8):
                    page.mouse.wheel(0, 1600)
                    page.wait_for_timeout(2_000)

                try:
                    documents.append(
                        page.locator("html").inner_text(timeout=10_000)
                    )
                except Exception:
                    pass

                try:
                    documents.append(page.content())
                except Exception:
                    pass

                for frame in page.frames:
                    try:
                        documents.append(frame.content())
                    except Exception:
                        pass
                    try:
                        documents.append(
                            frame.locator("body").inner_text(timeout=5_000)
                        )
                    except Exception:
                        pass

                collect(documents)
                if matches:
                    break

                print(
                    f"Agora goat listing not visible on attempt {attempt + 1}; "
                    "retrying..."
                )
        finally:
            browser.close()

    if not matches:
        # Agora can occasionally fail to expose its marketplace listing even
        # though the listing is still live. Do not break the whole Dakboard
        # update in that case: use the most recent successfully scraped price.
        history = load_history()
        if history:
            try:
                last_price = float(history[-1]["price"])
                print(
                    "Agora listing unavailable; using last successfully scraped "
                    f"Bourke goat price: {last_price:g} c/kg cwt"
                )
                return last_price, "last known", ""
            except (KeyError, TypeError, ValueError):
                pass

        raise RuntimeError(
            "Current Bourke goat processor grid not found in Agora listing data "
            "and no previous goat price is available"
        )

    def date_sort_key(item):
        try:
            return datetime.strptime(item[1], "%d %b %y")
        except ValueError:
            return datetime.min

    grid_text, date_text, price_dollars = max(matches, key=date_sort_key)
    price_cents = round(price_dollars * 100, 1)
    print(
        f"Agora Bourke goat grid {grid_text} ({date_text}): "
        f"${price_dollars:g}/kg HSCW "
        f"= {price_cents:g} c/kg cwt"
    )
    print(f"Agora raw grid price: {price_dollars:g}/kg HSCW")
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
