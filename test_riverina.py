import csv
import io
import requests

SHEETS = {
    "WHEAT": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQLKkdD8fOZJOtuFKhK0hs5u9Jr5WmB5IiP4CEILCMcCv4N66TwIRjXLKJPnRdC-Xf2u90vvqeL2cmE/pub?gid=0&single=true&output=csv",
    "BARLEY": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQeq8k64o3LvQpnOkUv2IoYIhLO_-qJrTIvnfzwJBhsBS67m6bzzEjaYt6XMwjk0ruerIceTRVCls46/pub?gid=0&single=true&output=csv",
}

TARGETS = ("hillston", "west wyalong", "apw1", "bar1")


def main():
    for name, url in SHEETS.items():
        print(f"\n=== {name} ===")
        response = requests.get(url, timeout=30, headers={"User-Agent": "wagga-feed/1.0"})
        response.raise_for_status()
        print(f"HTTP {response.status_code}; {len(response.content)} bytes")
        text = response.content.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
        print(f"Rows: {len(rows)}")

        matches = []
        for row in rows:
            joined = " | ".join(cell.strip() for cell in row)
            lower = joined.lower()
            if any(target in lower for target in TARGETS):
                matches.append(joined)

        if matches:
            print("Target matches:")
            for row in matches:
                print(row)
        else:
            print("No Hillston / West Wyalong / APW1 / BAR1 text found.")
            print("First 15 rows:")
            for row in rows[:15]:
                print(" | ".join(cell.strip() for cell in row))


if __name__ == "__main__":
    main()
