import html
import csv
import io
import re
import json
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path
from time import sleep, time
from zoneinfo import ZoneInfo

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
    separator = "&" if "?" in SOURCE_URL else "?"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; wagga-feed/1.0)",
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
    }

    # Agora can briefly return gateway errors. Retry before treating the
    # source as unavailable.
    for attempt in range(1, 4):
        fresh_url = f"{SOURCE_URL}{separator}wagga_feed_ts={int(time())}"
        try:
            response = requests.get(fresh_url, timeout=30, headers=headers)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                print(
                    f"Forbes Agora returned HTTP {response.status_code}; "
                    f"retrying ({attempt}/3)..."
                )
                sleep(2 * attempt)
                continue
            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as error:
            if attempt >= 3:
                raise
            print(f"Forbes Agora request failed ({attempt}/3): {error}; retrying...")
            sleep(2 * attempt)

    raise RuntimeError("Forbes Agora page could not be fetched after 3 attempts")


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
    # Log embedded spreadsheet URLs from the live Agora page so we can avoid
    # a stale published CSV if the page embeds a newer table.
    try:
        page = get_page()
        raw_html = str(page)
        embeds = [
            frame.get("src", "")
            for frame in page.find_all(["iframe", "embed"])
            if frame.get("src")
        ]
        sheet_urls = sorted(set(re.findall(
            r'https?[^"\\'\\s<>]*(?:docs\\.google\\.com|sheets\\.googleapis\\.com)[^"\\'\\s<>]*',
            raw_html,
            re.I,
        )))
        print("Forbes embedded table URLs:", embeds)
        print("Forbes Google Sheets source URLs:", sheet_urls)
        print("Forbes page contains current cow avg markers:", {
            "2366": "2,366" in raw_html,
            "2657": "2,657" in raw_html,
            "2190": "2,190" in raw_html,
            "2521": "2,521" in raw_html,
            "page_bytes": len(raw_html),
        })
    except Exception as error:
        print("Forbes could not inspect embedded table URLs:", error)

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; wagga-feed/1.0)",
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
    }
    errors = []
    for url in (
        TABLE_CSV_URL + f"&wagga_feed_ts={int(time())}",
        GVIZ_CSV_URL + f"&wagga_feed_ts={int(time())}",
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

    head_column = find_column("head")
    if head_column is None:
        raise ValueError("Forbes results table Head column not found")

    # Forbes has three separate price groups (Liveweight c/kg,
    # Carcass weight c/kg, and $/head). Each group uses generic Min/Max/Avg
    # subheaders, so identify the $/head group label first instead of assuming
    # the first Min/Max/Avg columns are dollar-per-head prices.
    group_row_index = None
    dollar_group_start = None
    for row_index in range(header_index, max(-1, header_index - 4), -1):
        for col_index, cell in enumerate(rows[row_index]):
            normalized = re.sub(r"\s+", "", clean(cell)).casefold()
            if "$/head" in normalized or "$perhead" in normalized or "dollar/head" in normalized:
                group_row_index = row_index
                dollar_group_start = col_index
                break
        if dollar_group_start is not None:
            break

    if dollar_group_start is None:
        raise ValueError("Forbes $/head price group heading not found")

    # If another named price group follows the $/head heading, stop at it;
    # otherwise the $/head group extends to the end of the header.
    group_row = [clean(cell).casefold() for cell in rows[group_row_index]]
    dollar_group_end = len(header)
    for col_index in range(dollar_group_start + 1, len(group_row)):
        label = group_row[col_index]
        if label and any(term in label for term in ("liveweight", "carcass", "$/head", "$ per head", "dollar/head")):
            dollar_group_end = col_index
            break

    # Keep the discovered Min/Max/Avg labels in their actual CSV positions.
    # The header labels are generic across price groups, so print the relevant
    # raw headers and target rows for diagnosis if Agora changes its layout.
    price_labels = {}
    for i in range(dollar_group_start, min(dollar_group_end, len(header))):
        label = re.sub(r"[^a-z]", "", header[i])
        if label in {"min", "max", "avg", "average"}:
            price_labels[label] = i

    dollar_avg = price_labels.get("avg") or price_labels.get("average")
    if (
        price_labels.get("min") is None
        or dollar_avg is None
        or price_labels.get("max") is None
    ):
        raise ValueError(
            "Forbes $/head Min, Max, Avg columns not found in the identified "
            "price group: "
            + repr({"group_row": group_row, "subheaders": header, "start": dollar_group_start, "end": dollar_group_end})
        )
    print(
        "Forbes using $/head columns:",
        {"min": price_labels["min"], "max": price_labels["max"], "avg": dollar_avg},
    )

    print("Forbes $/head header diagnostics:", {
        "group_row_index": group_row_index,
        "group_row": group_row,
        "header_index": header_index,
        "price_labels": price_labels,
        "header_cells": [(i, cell) for i, cell in enumerate(header) if i >= max(0, dollar_group_start - 3) and i < min(len(header), dollar_group_start + 8)],
    })

    columns = {
        "category": find_column("category - nsw", default=0),
        "range": find_column("range - nsw", default=1),
        "sale_prefix": find_column("sale prefix - nsw", default=2),
        "score": find_column("muscle score - nsw", default=3),
        "score_number": find_column("fat score - nsw", default=4),
        "dollar_avg": dollar_avg,
    }

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

        if (
            current_category.casefold() == "cows"
            and current_range.replace(" ", "").casefold() == "520+"
            and normalise_sale_prefix(current_prefix) == "pr"
            and clean(cells[columns["score_number"]]).replace(".0", "") in {"2", "3", "4"}
        ):
            print("Forbes cow raw CSV row:", {
                "score_number": cells[columns["score_number"]],
                "cells_near_dollar_group": [(i, cells[i]) for i in range(max(0, dollar_group_start - 3), min(len(cells), dollar_group_start + 8))],
                "selected_avg_index": dollar_avg,
                "selected_avg_value": cells[dollar_avg],
            })

        score = cells[columns["score"]]
        score_number = cells[columns["score_number"]]
        avg = parse_number(cells[columns["dollar_avg"]])

        if not (current_category and current_range and current_prefix and score_number and avg is not None):
            continue

        if avg <= 0:
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
    # Log the exact selected rows and source values so a changed Agora/Sheets
    # column layout is immediately visible in Actions rather than silently
    # producing a plausible but incorrect average.
    for row in records:
        if (
            clean(row["category"]).casefold() == "cows"
            and clean(row["range"]).replace(" ", "").casefold() == "520+"
            and normalise_sale_prefix(row["sale_prefix"]) == "pr"
            and clean(row["score_number"]).replace(".0", "") in {"2", "3", "4"}
        ):
            print("Forbes cow source row:", row)
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
        try:
            page = get_page()
        except requests.RequestException:
            # Forbes cattle sale is on Monday. If Agora is unavailable on
            # Sunday, that is before the next sale: retain the current feed
            # and finish successfully rather than flagging a false failure.
            local_now = datetime.now(ZoneInfo("Australia/Sydney"))
            if local_now.weekday() == 6:
                print(
                    "Forbes Agora is unavailable on Sunday, before the Monday "
                    "cattle sale. Keeping the existing cattle feed; no sale "
                    "update is expected yet."
                )
                return
            raise

        page_text = get_page_text(page)
        report_date = parse_report_date(page_text)
        if report_date is None:
            raise ValueError("Forbes report date not found on Agora page")

        report_age_days = (datetime.now(timezone.utc).date() - report_date.date()).days
        # A long weekend or cancelled sale can leave Agora showing the last
        # genuine sale for more than a week. Keep the existing feed and finish
        # successfully when no newer sale is published, instead of treating
        # that expected gap as a scraper failure.
        if report_age_days < 0:
            raise ValueError(
                f"Forbes cattle report is future-dated: "
                f"{report_date.strftime('%d %B %Y')} ({report_age_days} days from today)"
            )
        if report_age_days > 14:
            raise ValueError(
                f"Forbes cattle report is too old to trust: "
                f"{report_date.strftime('%d %B %Y')} ({report_age_days} days old; "
                f"maximum allowed age is 14 days)"
            )
        if report_age_days > 7:
            print(
                f"No newer Forbes cattle sale is published by Agora. "
                f"Keeping the existing feed for the {report_date.strftime('%d %B %Y')} sale "
                f"({report_age_days} days old); this is not a scraper failure."
            )
            return

        yarding = parse_yarding(page_text)
        if yarding is None:
            raise ValueError("Forbes total yarding not found")

        results_csv = fetch_results_csv()
        results = parse_results_table(results_csv)

        current = {}
        selected_scores = {}
        for key, target in TARGETS.items():
            current[key], selected_scores[key] = find_target_values(results, target)

        print("Forbes selected cow fat scores:", selected_scores["cows"])
        print("Forbes selected feeder fat scores:", selected_scores["feeder"])

        if current["cows"] is None:
            raise ValueError("Forbes table values not found: Cows > 520+ > Processor with fat score 2 or 3")
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
            f"<strong>Cows (&gt;500kg):</strong><br>av ${current['cows']:,.0f} ({cow_change})"
            if current["cows"] is not None
            else "<strong>Cows (&gt;500kg):</strong><br>Unavailable"
        )
        feeder_line = (
            f"<strong>Feeder Steers (330-400kg):</strong><br>av ${current['feeder']:,.0f} ({feeder_change})"
        )
        description = (
            "<br>" + cow_line + "<br><br>"
            + feeder_line + "<br><br>"
            f"<em>Yarding: {yarding:,} head</em><br>"
            f"<em>{yarding_change}</em>"
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