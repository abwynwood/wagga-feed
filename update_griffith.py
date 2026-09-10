#!/usr/bin/env python3
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://agoralivestock.com.au/saleyard-griffith-sheep/"
OUTPUT_FILE = Path(__file__).with_name("griffith.xml")


def get_text():
response = requests.get(
SOURCE_URL,
timeout=30,
headers={"User-Agent": "wagga-feed/1.0"},
)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")
return re.sub(
r"\s+",
" ",
html.unescape(soup.get_text(" ", strip=True)),
).strip()


def find(pattern, text):
return re.search(pattern, text, re.IGNORECASE | re.DOTALL)


def get_range(patterns, text):
for pattern in patterns:
match = find(pattern, text)

if match:
low = int(match.group(1).replace(",", ""))
high = int(match.group(2).replace(",", ""))

return f"${low:,}/hd – ${high:,}/hd"

return "No price reported"


def main():
text = get_text()

date_match = find(
r"Report Date:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})",
text,
)

yarding_match = find(
r"Total Yarding:\s*([\d,]+)",
text,
)

if not date_match or not yarding_match:
raise RuntimeError(
"Agora Griffith date/yarding not found"
)

# ---------------------------------------------------------
# LIGHT / RESTOCKER LAMBS
# ---------------------------------------------------------

light_lambs = get_range(
[
r"restocker lambs?.{0,150}?\$([\d,]+)\s*(?:-|to)\s*\$([\d,]+)/head",
r"store lambs?.{0,150}?\$([\d,]+)\s*(?:-|to)\s*\$([\d,]+)/head",
],
text,
)

# ---------------------------------------------------------
# TRADE / HEAVY LAMBS
# ---------------------------------------------------------

trade_lambs = get_range(
[
r"trade weights sold from \$([\d,]+) to \$([\d,]+)/head",
r"trade to heavy lambs?.{0,150}?\$([\d,]+) to \$([\d,]+)/head",
r"trade lambs?.{0,150}?\$([\d,]+) to \$([\d,]+)/head",
],
text,
)

# ---------------------------------------------------------
# MUTTON
# ---------------------------------------------------------

mutton_prices = []

patterns = [
r"ewes?.{0,120}?reaching \$([\d,]+)/head",
r"sheep?.{0,120}?reaching \$([\d,]+)/head",
r"mutton?.{0,120}?\$([\d,]+) to \$([\d,]+)/head",
]

for pattern in patterns:
match = find(pattern, text)

if match:
numbers = [
int(number.replace(",", ""))
for number in match.groups()
if number
]

mutton_prices.extend(numbers)

if mutton_prices:
mutton_low = min(mutton_prices)
mutton_high = max(mutton_prices)

mutton = (
f"${mutton_low:,}/hd – "
f"${mutton_high:,}/hd"
)
else:
mutton = "No price reported"

# ---------------------------------------------------------
# MARKET DIRECTION
# ---------------------------------------------------------

if re.search(
r"stronger trend|prices were stronger|prices averaged dearer",
text,
re.IGNORECASE,
):
market = "FIRM"

elif re.search(
r"\bsofter\b|\bcheaper\b|\beased\b",
text,
re.IGNORECASE,
):
market = "SOFTER"

else:
market = "STEADY"

# ---------------------------------------------------------
# SHORT MARKET SUMMARY
# ---------------------------------------------------------

if market == "FIRM":
summary = "Market sold to a stronger trend."

elif market == "SOFTER":
summary = "Prices softer across the market."

else:
summary = "Prices mostly steady."

# ---------------------------------------------------------
# BUILD XML FEED
# ---------------------------------------------------------

root = ET.Element(
"rss",
version="2.0",
)

channel = ET.SubElement(
root,
"channel",
)

ET.SubElement(
channel,
"title",
).text = "Griffith Sheep Sale"

ET.SubElement(
channel,
"link",
).text = SOURCE_URL

item = ET.SubElement(
channel,
"item",
)

ET.SubElement(
item,
"title",
).text = f"Griffith Sheep Sale — {date_match.group(1)}"

description = "\n".join(
[
f"GRIFFITH SHEEP SALE — {date_match.group(1)}",
"",
f"Light Lambs: {light_lambs}",
f"Trade/Heavy Lambs: {trade_lambs}",
f"Mutton: {mutton}",
"",
f"Yarding: {yarding_match.group(1)} head",
f"Market: {market}",
f"Summary: {summary}",
]
)

ET.SubElement(
item,
"description",
).text = description

ET.SubElement(
item,
"pubDate",
).text = datetime.now(
timezone.utc
).strftime(
"%a, %d %b %Y %H:%M:%S +0000"
)

ET.SubElement(
item,
"guid",
).text = SOURCE_URL

ET.ElementTree(root).write(
OUTPUT_FILE,
encoding="utf-8",
xml_declaration=True,
)


if __name__ == "__main__":
try:
main()

except Exception as error:
# If Agora temporarily fails, keep the last successful feed.
if OUTPUT_FILE.exists():
print(
"Update failed; retaining previous feed:",
error,
)
else:
raise
