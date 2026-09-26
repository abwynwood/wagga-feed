import html
import csv
import io
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


def get_page():
    response = requests.get(
        SOURCE_URL,
        timeout=30,
        headers={"User-Agent": "wagga-feed/1.0"},
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def get_page_text(soup):
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
        SHEET_CSV_URL + f"&_={int(time())}",
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; wagga-feed/1.0)",
            "Cache-Control": "no-cache, no-store, max-age=0",
        },
    )
    response.raise_for_status()
    if "Category - NSW" not in response.text:
        raise ValueError("Forbes published results CSV did not contain the expected table")
    return response.text
def parse_results_table(csv_text):
    rows = list(csv.reader(io.StringIO(csv_text)))
    header_index = None
    for i, row in enumerate(rows):
        joined = " | ".join(clean(cell) for cell in row).casefold()
        if "category - nsw" in joined and "range - nsw" in joined and "sale prefix - nsw" in joined:
            header_index = i
            break
    if header_index is None:
        raise ValueError("Forbes results table header not found")

    header = [clean(cell).casefold() for cell in rows[header_index]]
    avg_index = None
    for i, cell in enumerate(header):
        if "$/head" in cell and "avg" in cell:
            avg_index = i
            break
    if avg_index is None:
        avg_index = len(header) - 2

    records = []
    current_category = ""
    current_range = ""
    current_prefix = ""
    for raw in rows[header_index + 1:]:
        cells = [clean(v) for v in raw]
        if len(cells) < 6:
            continue
        cells += [""] * max(0, len(header) - len(cells))
        current_category = cells[0] or current_category
        current_range = cells[1] or current_range
        current_prefix = cells[2] or current_prefix
        score = cells[3] if len(cells) > 3 else ""
        score_number = cells[4] if len(cells) > 4 else ""
        avg = parse_number(cells[avg_index]) if avg_index < len(cells) else None
        if not (current_category and current_range and current_prefix and score and score_number and avg is not None):
            continue
        records.append({"category": current_category, "range": current_range, "sale_prefix": current_prefix, "score": score, "score_number": score_number, "dollar_avg": avg})
    return records
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
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")


def comparison_arrow(current, previous):
    if current is None or previous is None:
        return "➡️ $0/hd"

    change = round(current - previous)
    if change > 0:
        return f"⬆️ {chr(36)}{change}/hd"
    if change < 0:
        return f"⬇️ {chr(36)}{abs(change)}/hd"
    return "➡️ $0/hd"


def main():
    try:
        page = get_page()
        page_text = get_page_text(page)
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
            f"<strong>Cows (&gt;500kg):</strong> av {chr(36)}{current['cows']:,.0f} ({cow_change})<br>"
            f"<strong>Feeder Steers (330-400kg):</strong> av {chr(36)}{current['feeder']:,.0f} ({feeder_change})"
        )

        history[sale_key] = {
            "cows": round(current["cows"], 2),
            "feeder": round(current["feeder"], 2),
        }

        dated_history = {
            key: value for key, value in history.items()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", key)
        }
        save_history(dict(sorted(dated_history.items())[-12:]))

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
