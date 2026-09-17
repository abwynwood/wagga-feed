import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

TFI_SUPPLIERS_URL = "https://thomasfoods.com/livestock-suppliers/"
OUTPUT_FILE = Path(__file__).with_name("goats.xml")
HISTORY_FILE = Path(__file__).with_name("goat_history.json")


def fetch_bourke_grid():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; wagga-feed/1.0)"}
    response = requests.get(TFI_SUPPLIERS_URL, headers=headers, timeout=60)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    goat_pdf_url = None
    for link in soup.find_all("a", href=True):
        href = link["href"]
        label = link.get_text(" ", strip=True).lower()
        if "goat-grid" in href.lower() or ("pricing grid" in label and "goat" in label):
            goat_pdf_url = href
            break

    if not goat_pdf_url:
        # Fall back to any PDF link whose URL identifies it as a goat grid.
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if ".pdf" in href.lower() and "goat" in href.lower():
                goat_pdf_url = href
                break

    if not goat_pdf_url:
        raise RuntimeError("Current Thomas Foods goat grid PDF link not found")

    if goat_pdf_url.startswith("/"):
        goat_pdf_url = "https://thomasfoods.com" + goat_pdf_url
    elif goat_pdf_url.startswith("//"):
        goat_pdf_url = "https:" + goat_pdf_url

    pdf_response = requests.get(goat_pdf_url, headers=headers, timeout=60)
    pdf_response.raise_for_status()

    import io
    reader = PdfReader(io.BytesIO(pdf_response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    text = re.sub(r"[ \t]+", " ", text)

    # Locate the Bourke HSCW goat section and take the first dollar figure
    # belonging to that section.
    bourke = re.search(r"BOURKE\b(.*?)(?=\n[A-Z][A-Z &-]{3,}\b|$)", text, re.I | re.S)
    section = bourke.group(1) if bourke else text
    match = re.search(r"HSCW\s+GOATS.*?\$\s*(\d+(?:\.\d+)?)", section, re.I | re.S)
    if not match:
        match = re.search(r"BOURKE.*?HSCW\s+GOATS.*?\$\s*(\d+(?:\.\d+)?)", text, re.I | re.S)
    if not match:
        raise RuntimeError("Current Bourke goat price not found in Thomas Foods goat grid PDF")

    price_dollars = float(match.group(1))
    grid_match = re.search(r"Goat\s+Grid\s+([0-9]+)", text, re.I)
    date_match = re.search(r"\b(\d{2}[./]\d{2}[./]\d{4})\b", text)
    grid_number = grid_match.group(1) if grid_match else "current"
    date_text = date_match.group(1) if date_match else ""

    price_cents = round(price_dollars * 100, 1)
    print(f"Thomas Foods Bourke goat grid {grid_number} ({date_text}): ${price_dollars:g}/kg HSCW = {price_cents:g} c/kg cwt")
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
    date_suffix = f" ({date_text})" if date_text else ""
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Bourke Goat Processor Grid</title>
    <link>{TFI_SUPPLIERS_URL}</link>
    <description>Current Thomas Foods International Bourke goat processor grid</description>
    <language>en-au</language>
    <item>
      <title>Bourke Goat Grid {grid_number}{date_suffix}</title>
      <link>{TFI_SUPPLIERS_URL}</link>
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
