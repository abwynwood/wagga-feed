import html
import csv
import io
import re
import json
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path
from time import time

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://agoralivestock.com.au/saleyard-forbes-cattle/"
GVIZ_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vTJCYUTqmjXBC_SfhIIE-dzxih0HwuiTjLqIats2wurbtEmW8zs-6DiNtBxqTs_HQvkps6Pey63q4kV/"
    "gviz/tq?tqx=out:csv&gid=161375687"
)

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
    },
    "feeder": {
        "label": "Feeder Steers (330-400kg)",
        "category": "Yearling Steer",
        "range": "330-400",
        "sale_prefix": "Feeder",
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


def parse_yarding(text):
    match = re.search(r"Total\s+Yarding\s*:\s*([\d,]+)", text, re.I)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


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
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; wagga-feed/1.0)",
        "Cache-Control": "no-cache, no-store, max-age=0",
    }
    errors = []
    for url in (
        TABLE_CSV_URL + f"&_={int(time())}",
        GVIZ_CSV_URL + f"&_={int(time())}",
    ):
        try:
            response = requests.get(url, timeout=30, headers=headers)
            response.raise_for_status()
            if "Category - NSW" in response.text and "Range - NSW" in response.text:
                print(f"Forbes results CSV loaded: {len(response.text)} bytes")
                return response.text
            errors.append("unexpected response from " + url)
        except Exception as error:
            errors.append(str(error))
    raise ValueError("Forbes published CSV unavailable: " + " | ".join(errors))
def parse_results_table(csv_text):
    rows = list(csv.reader(io.StringIO(csv_text)))
    header_index = None

    for i, row in enumerate(rows):
        joined = " | ".join(clean(cell) for cell in row).casefold()
        if (
            "category - nsw" in joined
            and "range - nsw" in joined
            and "sale prefix - nsw" in joined
        ):
            header_index = i
            break

    if header_index is None:
        raise ValueError("Forbes results table header not found")

    header = [clean(cell).casefold() for cell in rows[header_index]]

    def find_column(*needles, default=None):
        for i, cell in enumerate(header):
            if all(needle in cell for needle in needles):
                return i
        return default

    columns = {
        "category": find_column("category - nsw", default=0),
        "range": find_column("range - nsw", default=1),
        "sale_prefix": find_column("sale prefix - nsw", default=2),
        "score": find_column("muscle score - nsw", default=3),
        "score_number": find_column("fat score - nsw", default=4),
        # In the Forbes published table the final three columns are\n        # $/head Min, Avg and Max. The middle of those three is Avg.\n        "dollar_avg": len(header) - 2,
    }

    if columns["dollar_avg"] is None:
        raise ValueError("Forbes $/head Avg column not found")

    records = []
    current_category = ""
    current_range = ""
    current_prefix = ""

    for raw in rows[header_index + 1:]:
        cells = [clean(v) for v in raw]
        cells += [""] * max(0, len(header) - len(cells))

        if cells[columns["category"]]:
            current_category = cells[columns["category"]]
        if cells[columns["range"]]:
            current_range = cells[columns["range"]]
        if cells[columns["sale_prefix"]]:
            current_prefix = cells[columns["sale_prefix"]]

        score = cells[columns["score"]]
        score_number = cells[columns["score_number"]]
        avg = parse_number(cells[columns["dollar_avg"]])

        if not (current_category and current_range and current_prefix and score_number and avg is not None):
            continue

        records.append({
            "category": current_category,
            "range": current_range,
            "sale_prefix": current_prefix,
            "score": score,
            "score_number": score_number,
            "dollar_avg": avg,
        })

    print("Forbes parsed records:", len(records))
    return records



def normalise_sale_prefix(value):
    value = clean(value).casefold()
    aliases = {
        "processor": "pr",
        "pr": "pr",
        "feeder": "fd",
        "fd": "fd",
        "restocker": "rs",
        "rs": "rs",
    }
    return aliases.get(value, value)


def find_target_values(results, target):
    target_category = clean(target["category"]).casefold()
    target_range = clean(target["range"]).replace(" ", "").casefold()
    target_prefix = normalise_sale_prefix(target["sale_prefix"])

    by_score = {}
    for row in results:
        if (
            clean(row["category"]).casefold() == target_category
            and clean(row["range"]).replace(" ", "").casefold() == target_range
            and normalise_sale_prefix(row["sale_prefix"]) == target_prefix
            and clean(row["score_number"]).replace(".0", "") in {"2", "3"}
        ):
            by_score[clean(row["score_number"]).replace(".0", "")] = row["dollar_avg"]

    selected = [by_score[str(score)] for score in (2, 3) if str(score) in by_score]
    if not selected:
        return None, {}
    return sum(selected) / len(selected), by_score



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


def comparison_head_arrow(current, previous):
    if current is None or previous is None:
        return "→ 0 head"

    change = round(current - previous)
    if change > 0:
        return f"↑ {change:,} head"
    if change < 0:
        return f"↓ {abs(change):,} head"
    return "→ 0 head"


def comparison_arrow(current, previous):
    if current is None or previous is None:
        return "→ $0/hd"

    change = round(current - previous)
    if change > 0:
        return f"↑ ${change}/hd"
    if change < 0:
        return f"↓ ${abs(change)}/hd"
    return "→ $0/hd"


def main():
    try:
        page = get_page()
        page_text = get_page_text(page)
        report_date = parse_report_date(page_text)
        yarding = parse_yarding(page_text)
        if yarding is None:
            raise ValueError("Forbes total yarding not found")

        if report_date is None:
            raise ValueError("Forbes report date not found on Agora page")

        results_csv = fetch_results_csv()
        results = parse_results_table(results_csv)

        current = {}
        selected_scores = {}
        for key, target in TARGETS.items():
            current[key], selected_scores[key] = find_target_values(results, target)

        print("Forbes selected cow fat scores:", selected_scores["cows"])
        print("Forbes selected feeder fat scores:", selected_scores["feeder"])

        if current["feeder"] is None:
            raise ValueError("Forbes table values not found: Yearling Steer > 330-400 > Feeder with fat score 2 or 3")

        history = load_history()
        sale_key = (report_date or datetime.now(timezone.utc)).strftime("%Y-%m-%d")

        previous = {}
        dated_keys = sorted(
            k for k in history if re.fullmatch(r"\d{4}-\d{2}-\d{2}", k)
        )
        earlier = [k for k in dated_keys if k < sale_key]
        if earlier:
            previous = history[earlier[-1]]

        cow_change = comparison_arrow(
            current["cows"], previous.get("cows")
        ) if current["cows"] is not None else None
        feeder_change = comparison_arrow(
            current["feeder"], previous.get("feeder")
        )
        yarding_change = comparison_head_arrow(
            yarding, previous.get("yarding")
        )

        cow_line = (
            f"<strong>Cows (&gt;500kg):</strong> av ${current['cows']:,.0f} ({cow_change})"
            if current["cows"] is not None
            else "<strong>Cows (&gt;500kg):</strong> Unavailable"
        )
        description = (
            cow_line + "<br>"
            f"<strong>Feeder Steers (330-400kg):</strong> av ${current['feeder']:,.0f} ({feeder_change})<br>"
            f"<em>Yarding: {yarding:,} head ({yarding_change})</em>"
        )

        history_entry = {
            "feeder": round(current["feeder"], 2),
            "yarding": yarding,
        }
        if current["cows"] is not None:
            history_entry["cows"] = round(current["cows"], 2)
        history[sale_key] = history_entry

        dated_history = {
            key: value
            for key, value in history.items()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", key)
        }
        save_history(dict(sorted(dated_history.items())[-12:]))

        now = datetime.now(timezone.utc)
        xml = f'''<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Forbes Cattle Sale</title><link>{SOURCE_URL}</link><item><title>Forbes Cattle Sale — {date_title(report_date, now)}</title><description><![CDATA[{description}]]></description><pubDate>{formatdate(now.timestamp(), usegmt=True)}</pubDate><guid>{SOURCE_URL}</guid></item></channel></rss>'''

        OUTPUT_FILE.write_text(xml, encoding="utf-8")
        print(description.replace("<br>", " | "))

    except Exception as error:
        print("Forbes cattle update FAILED:", error)
        raise


if __name__ == "__main__":
    main()