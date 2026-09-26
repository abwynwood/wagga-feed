import csv
import html
import io
import re
import json
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://agoralivestock.com.au/saleyard-forbes-cattle/"
TABLE_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vTJCYUTqmjXBC_SfhIIE-dzxih0HwuiTjLqIats2wurbtEmW8zs-6DiNtBxqTs_HQvkps6Pey63q4kV/"
    "pub?gid=161375687&single=true&output=csv"
)
OUTPUT_FILE = Path(__file__).with_name("wagga_cattle.xml")
HISTORY_FILE = Path(__file__).with_name("forbes_cattle_history.json")

TARGETS = {
    "cows": {
        "label": "Cows (>500kg)",
        "category": "Cows",
        "range": "520+",
        "sale_prefix": "Processor",
        "score": "D",
        "score_number": "4",
    },
    "feeder": {
        "label": "Feeder Steers (330-400kg)",
        "category": "Yearling Steer",
        "range": "330-400",
        "sale_prefix": "Feeder",
        "score": "C",
        "score_number": "2",
    },
}


def clean(value):
    return re.sub(r"\s+", " ", (value or "").strip())


def get_page_text():
    response = requests.get(
        SOURCE_URL,
        timeout=30,
        headers={"User-Agent": "wagga-feed/1.0"},
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_report_date(text):
    match = re.search(
        r"\bReport\s+Date\s*:?\s*[\s-]*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})",
        text,
        re.I,
    )
    if not match:
        return None
    try:
        return datetime.strptime(
            f"{match.group(1)} {match.group(2)} {match.group(3)}",
            "%d %B %Y",
        )
    except ValueError:
        return None


def date_title(report_date, fallback):
    date = report_date or fallback
    day = date.day
    suffix = "th" if 10 < day % 100 < 14 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {date.strftime('%B %Y')}"


def parse_number(value):
    value = clean(value).replace("$", "").replace(",", "")
    if not value or value.upper() in {"NQ", "NA", "N/A", "-"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def fetch_results_csv():
    response = requests.get(
        TABLE_CSV_URL,
        timeout=30,
        headers={"User-Agent": "wagga-feed/1.0"},
    )
    response.raise_for_status()
    return response.text


def parse_results_table(csv_text):
    rows = list(csv.reader(io.StringIO(csv_text)))
    header_index = None

    for i, row in enumerate(rows):
        normalized = [clean(cell).lower() for cell in row]
        if (
            "category - nsw" in normalized
            and "range - nsw" in normalized
            and "sale prefix - nsw" in normalized
        ):
            header_index = i
            break

    if header_index is None:
        raise ValueError("Forbes results table header not found")

    header = [clean(cell).lower() for cell in rows[header_index]]
    avg_index = None

    for i, cell in enumerate(header):
        if cell in {"$/head avg", "$ / head avg", "$/head - avg", "$ / head - avg"}:
            avg_index = i
            break

    if avg_index is None:
        avg_index = len(header) - 2

    results = []
    current_category = ""
    current_range = ""
    current_prefix = ""

    for raw_row in rows[header_index + 1:]:
        row = [clean(cell) for cell in raw_row]
        if not any(row):
            continue

        row += [""] * max(0, len(header) - len(row))

        if row[0]:
            current_category = row[0]
        if row[1]:
            current_range = row[1]
        if row[2]:
            current_prefix = row[2]

        score = row[3] if len(row) > 3 else ""
        score_number = row[4] if len(row) > 4 else ""
        dollar_avg = parse_number(row[avg_index]) if avg_index < len(row) else None

        if not score or not score_number or dollar_avg is None:
            continue

        results.append({
            "category": current_category,
            "range": current_range,
            "sale_prefix": current_prefix,
            "score": score,
            "score_number": score_number,
            "dollar_avg": dollar_avg,
        })

    return results


def find_target(results, target):
    for row in results:
        if (
            row["category"].casefold() == target["category"].casefold()
            and row["range"].replace(" ", "") == target["range"].replace(" ", "")
            and row["sale_prefix"].casefold() == target["sale_prefix"].casefold()
            and row["score"].casefold() == target["score"].casefold()
            and row["score_number"] == target["score_number"]
        ):
            return row["dollar_avg"]
    return None


def load_history():
    if not HISTORY_FILE.exists():
        return {}
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")


def comparison_arrow(current, previous):
    if current is None or previous is None:
        return "➡️ $0/hd"
    change = round(current - previous)
    if change > 0:
        return f"⬆️ ${change}/hd"
    if change < 0:
        return f"⬇️ ${abs(change)}/hd"
    return "➡️ $0/hd"


def main():
    try:
        page_text = get_page_text()
        report_date = parse_report_date(page_text)

        results = parse_results_table(fetch_results_csv())
        current = {key: find_target(results, target) for key, target in TARGETS.items()}

        missing = [TARGETS[key]["label"] for key, value in current.items() if value is None]
        if missing:
            raise ValueError("Forbes table values not found: " + ", ".join(missing))

        history = load_history()
        sale_key = (report_date or datetime.now(timezone.utc)).strftime("%Y-%m-%d")

        previous = {}
        dated_keys = sorted(k for k in history if re.fullmatch(r"\d{4}-\d{2}-\d{2}", k))
        earlier = [k for k in dated_keys if k < sale_key]
        if earlier:
            previous = history[earlier[-1]]

        cow_change = comparison_arrow(current["cows"], previous.get("cows"))
        feeder_change = comparison_arrow(current["feeder"], previous.get("feeder"))

        description = (
            f"<strong>Cows (&gt;500kg):</strong> av ${current['cows']:,.0f} ({cow_change})<br>"
            f"<strong>Feeder Steers (330-400kg):</strong> av ${current['feeder']:,.0f} ({feeder_change})"
        )

        history[sale_key] = {
            "cows": round(current["cows"], 2),
            "feeder": round(current["feeder"], 2),
        }
        save_history(dict(sorted(history.items())[-12:]))

        now = datetime.now(timezone.utc)
        xml = f'''<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Forbes Cattle Sale</title><link>{SOURCE_URL}</link><item><title>Forbes Cattle Sale — {date_title(report_date, now)}</title><description><![CDATA[{description}]]></description><pubDate>{formatdate(now.timestamp(), usegmt=True)}</pubDate><guid>{SOURCE_URL}</guid></item></channel></rss>'''
        OUTPUT_FILE.write_text(xml, encoding="utf-8")
        print(description.replace("<br>", " | "))

    except Exception as error:
        if OUTPUT_FILE.exists():
            print("Update failed; retaining previous feed:", error)
        else:
            raise


if __name__ == "__main__":
    main()
