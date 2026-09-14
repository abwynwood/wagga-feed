import html
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://agoralivestock.com.au/saleyard-wagga-cattle/"
OUTPUT_FILE = Path(__file__).with_name("wagga_cattle.xml")


def get_text():
    response = requests.get(
        SOURCE_URL,
        timeout=30,
        headers={"User-Agent": "wagga-feed/1.0"},
    )
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
        return "Not reported"
    return "%d–%dc/kg" % (min(values), max(values))


def market_direction(text):
    lower = text.lower()
    if any(word in lower for word in ["strong", "stronger", "firmer", "dearer", "lifted", "gained", "competitive"]):
        return "FIRM"
    if any(word in lower for word in ["softer", "cheaper", "easier", "eased", "weaker", "declined"]):
        return "SOFTER"
    return "STEADY"


def main():
    try:
        text = get_text()

        feeder = cents_range([
            r"\b(?:Light|Heavy)\s+feeder steers\b[^.]{0,180}?\bfrom\s+([\d,]+)\s*c/kg\s*(?:to|-|–)\s*([\d,]+)\s*c/kg",
            r"\bMedium[-\s]+weight feeder steers\b[^.]{0,180}?\bfrom\s+([\d,]+)\s*c/kg\s*(?:to|-|–)\s*([\d,]+)\s*c/kg",
            r"\bFeeder steers\b[^.]{0,220}?\bfrom\s+([\d,]+)\s*c/kg\s*(?:to|-|–)\s*([\d,]+)\s*c/kg",
        ], text)

        cows = cents_range([
            r"\bHeavy cows\b[^.]{0,180}?\bfrom\s+([\d,]+)\s*c/kg\s*(?:to|-|–)\s*([\d,]+)\s*c/kg",
            r"\bLeaner(?: types)?\b[^.]{0,180}?\bfrom\s+([\d,]+)\s*c/kg\s*(?:to|-|–)\s*([\d,]+)\s*c/kg",
        ], text)

        yarding_match = re.search(r"Total Yarding\s*[:\-]?\s*([\d,]+)\s*head", text, re.I)
        yarding = f"{yarding_match.group(1)} head" if yarding_match else "Not reported"

        direction = market_direction(text)
        summary = "Market firm to stronger." if direction == "FIRM" else "Market steady." if direction == "STEADY" else "Market softer."

        description = (
            f"Feeder Steers: {feeder}<br>"
            f"Cows: {cows}<br><br>"
            f"Yarding: {yarding}<br>"
            f"Market: {direction}<br>"
            f"Summary: {summary}"
        )

        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Wagga Cattle Market</title>
    <description><![CDATA[{description}]]></description>
  </channel>
</rss>
'''
        OUTPUT_FILE.write_text(xml, encoding="utf-8")
        print(description.replace("<br>", " | "))

    except Exception as error:
        if OUTPUT_FILE.exists():
            print("Update failed; retaining previous feed:", error)
        else:
            raise


if __name__ == "__main__":
    main()
