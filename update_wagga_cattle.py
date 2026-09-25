import html
import re
import json
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://agoralivestock.com.au/saleyard-forbes-cattle/"
OUTPUT_FILE = Path(__file__).with_name("wagga_cattle.xml")
HISTORY_FILE = Path(__file__).with_name("forbes_cattle_history.json")


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


def category_value(value_range):
    if value_range is None:
        return None
    return (value_range[0] + value_range[1]) / 2


def load_previous():
    if not HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_history(current):
    HISTORY_FILE.write_text(json.dumps(current), encoding="utf-8")


def comparison_arrow(current, previous):
    if current is None or previous is None:
        return "➡️ $0/hd"
    change = round(current - previous)
    if change > 0:
        return f"⬆️ ${change}/hd"
    if change < 0:
        return f"⬇️ ${abs(change)}/hd"
    return "➡️ $0/hd"


def date_title(report_date, fallback):
    if report_date:
        day = report_date.day
        suffix = "th" if 10 < day % 100 < 14 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"{day}{suffix} {report_date.strftime('%B %Y')}"
    day = fallback.day
    suffix = "th" if 10 < day % 100 < 14 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {fallback.strftime('%B %Y')}"


def main():
    try:
        text = get_text()

        report_date = None
        report_match = re.search(r"\\bReport\\s+Date\\s*:?[\\s-]*(\\d{1,2})(?:st|nd|rd|th)?\\s+([A-Za-z]+)\\s+(\\d{4})", text, re.I)
        if report_match:
            try:
                report_date = datetime.strptime(
                    f"{report_match.group(1)} {report_match.group(2)} {report_match.group(3)}",
                    "%d %B %Y",
                )
            except ValueError:
                report_date = None

        feeder_range = cents_range([
            r"\b(?:Light|Heavy)\s+feeder steers\b.{0,300}?\b(?:from\s+)?([\d,]+)\s*c/kg\s*(?:to|-)\s*([\d,]+)\s*c/kg",
            r"\bMedium[-\s]+weight feeder steers\b.{0,300}?\b(?:from\s+)?([\d,]+)\s*c/kg\s*(?:to|-)\s*([\d,]+)\s*c/kg",
            r"\b(?:Yearling|Feeder) steers\b.{0,350}?\bto feed\b.{0,150}?([\d,]+)\s*c(?:/kg)?\s*(?:to|-)\s*([\d,]+)\s*c/kg",
            r"\b(?:Yearling|Feeder) steers\b.{0,350}?([\d,]+)\s*c(?:/kg)?\s*(?:to|-)\s*([\d,]+)\s*c/kg",
            r"\bmiddle and heavyweights?\s+to feed\b.{0,150}?([\d,]+)\s*c(?:/kg)?\s*(?:to|-)\s*([\d,]+)\s*c/kg",
            r"\bFeeder steers\b.{0,350}?([\d,]+)\s*(?:-|to)\s*([\d,]+)\s*c/kg",
        ], text)

        cows_range = cents_range([
            r"\b(?:Heavy|Better finished heavy|Heavy finished) cows\b.{0,250}?([\d,]+)\s*c(?:/kg)?\s*(?:to|-)\s*([\d,]+)\s*c/kg",
            r"\b(?:Plainer|Leaner)(?: types)? cows?\b.{0,250}?([\d,]+)\s*c(?:/kg)?\s*(?:to|-)\s*([\d,]+)\s*c/kg",
            r"\bcows\b.{0,350}?([\d,]+)\s*c(?:/kg)?\s*(?:to|-)\s*([\d,]+)\s*c/kg",
        ], text)

        feeder = range_display(feeder_range)
        cows = range_display(cows_range)
        feeder_value = carcass_value(feeder_range, 300)
        cow_value = carcass_value(cows_range, 500)

        previous = load_previous()
        feeder_change = comparison_arrow(category_value(feeder_range), previous.get("feeder"))
        cow_change = comparison_arrow(category_value(cows_range), previous.get("cows"))

        yarding_match = re.search(r"Total Yarding\s*[:\-]?\s*([\d,]+)", text, re.I)
        yarding = f"{yarding_match.group(1)} head" if yarding_match else "Not reported"
        current_yarding = int(yarding_match.group(1).replace(",", "")) if yarding_match else None
        previous_yarding = previous.get("yarding")
        yarding_change = comparison_arrow(current_yarding, previous_yarding)

        description = (
            f"<br><strong>Feeder Steers:</strong> {feeder} <span>({feeder_change})</span><br>"
            f"<span> (300kg steer: {feeder_value})</span><br>"
            f"<br><strong>Cows:</strong> {cows} <span>({cow_change})</span><br>"
            f"<span>(500kg cow: {cow_value})</span><br>"
            f"<br><i>Yarding: {yarding} ({yarding_change})</i>"
        )

        now = datetime.now(timezone.utc)
        xml = f'''<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Forbes Cattle Sale</title><link>{SOURCE_URL}</link><item><title>Forbes Cattle Sale — {date_title(report_date, now)}</title><description><![CDATA[{description}]]></description><pubDate>{formatdate(now.timestamp(), usegmt=True)}</pubDate><guid>{SOURCE_URL}</guid></item></channel></rss>'''
        OUTPUT_FILE.write_text(xml, encoding="utf-8")

        save_history({
            "feeder": category_value(feeder_range),
            "cows": category_value(cows_range),
            "yarding": current_yarding,
        })
        print(description.replace("<br>", " | "))

    except Exception as error:
        if OUTPUT_FILE.exists():
            print("Update failed; retaining previous feed:", error)
        else:
            raise


if __name__ == "__main__":
    main()
