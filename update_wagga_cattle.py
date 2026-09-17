import html
import re
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://agoralivestock.com.au/saleyard-wagga-cattle/"
OUTPUT_FILE = Path(__file__).with_name("wagga_cattle.xml")


def get_text():
    response = requests.get(SOURCE_URL, timeout=30, headers={"User-Agent": "wagga-feed/1.0"})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = html.unescape(text).replace("\xa0", " ")
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    return re.sub(r"\s+", " ", text).strip()


def cents_range(patterns, text):
    values = []
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.I | re.S):
            values.extend(int(v.replace(",", "")) for v in m.groups() if v)
    if not values:
        return None
    return min(values), max(values)


def range_display(value):
    if value is None:
        return "Not reported"
    return "%d–%dc/kg" % value


def carcass_value(value_range, weight_kg):
    if value_range is None:
        return "Not reported"
    average_cents = (value_range[0] + value_range[1]) / 2
    value_dollars = average_cents * weight_kg / 100
    return f"${value_dollars:,.0f}"


def market_direction(text):
    lower = text.lower()
    if any(word in lower for word in ["strong", "stronger", "firmer", "dearer", "lifted", "gained", "competitive"]):
        return "FIRM"
    if any(word in lower for word in ["softer", "cheaper", "easier", "eased", "weaker", "declined"]):
        return "SOFTER"
    return "STEADY"


def date_title(now):
    day = now.day
    suffix = "th" if 10 < day % 100 < 14 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {now.strftime('%B %Y')}"


def main():
    try:
        text = get_text()

        # Agora's current report uses wording such as:
        # "Feeder steers 340-400kg ... 482 to 584c/kg".
        feeder_range = cents_range([
            r"\b(?:Light|Heavy)\s+feeder steers\b.{0,300}?\b(?:from\s+)?([\d,]+)\s*c/kg\s*(?:to|-)\s*([\d,]+)\s*c/kg",
            r"\bMedium[-\s]+weight feeder steers\b.{0,300}?\b(?:from\s+)?([\d,]+)\s*c/kg\s*(?:to|-)\s*([\d,]+)\s*c/kg",
            r"\bFeeder steers\b.{0,350}?\b(?:from\s+)?([\d,]+)\s*c/kg\s*(?:to|-)\s*([\d,]+)\s*c/kg",
            r"\bFeeder steers\b.{0,350}?([\d,]+)\s*(?:-|to)\s*([\d,]+)\s*c/kg",
        ], text)

        cows_range = cents_range([
            r"\bHeavy cows\b.{0,250}?\b(?:from\s+)?([\d,]+)\s*c/kg\s*(?:to|-)\s*([\d,]+)\s*c/kg",
            r"\bLeaner(?: types)?\b.{0,250}?\b(?:from\s+)?([\d,]+)\s*c/kg\s*(?:to|-)\s*([\d,]+)\s*c/kg",
        ], text)

        feeder = range_display(feeder_range)
        cows = range_display(cows_range)
        feeder_value = carcass_value(feeder_range, 300)
        cow_value = carcass_value(cows_range, 500)

        yarding_match = re.search(r"Total Yarding\s*[:\-]?\s*([\d,]+)", text, re.I)
        yarding = f"{yarding_match.group(1)} head" if yarding_match else "Not reported"

        direction = market_direction(text)
        summary = "Market firm to stronger." if direction == "FIRM" else "Market steady." if direction == "STEADY" else "Market softer."

        description = (
            f"Feeder Steers: {feeder}<br>"
            f"300kg steer: {feeder_value}<br>"
            f"Cows: {cows}<br>"
            f"500kg cow: {cow_value}<br>"
            f"Yarding: {yarding}<br>"
            f"Market: {direction}<br>"
            f"Summary: {summary}"
        )

        now = datetime.now(timezone.utc)
        xml = f'''<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Wagga Cattle Sale</title><link>{SOURCE_URL}</link><item><title>Wagga Cattle Sale — {date_title(now)}</title><description><![CDATA[{description}]]></description><pubDate>{formatdate(now.timestamp(), usegmt=True)}</pubDate><guid>{SOURCE_URL}</guid></item></channel></rss>'''
        OUTPUT_FILE.write_text(xml, encoding="utf-8")
        print(description.replace("<br>", " | "))

    except Exception as error:
        if OUTPUT_FILE.exists():
            print("Update failed; retaining previous feed:", error)
        else:
            raise


if __name__ == "__main__":
    main()
