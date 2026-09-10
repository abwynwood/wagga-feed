import csv
import io
import requests

SHEETS = {
    "WHEAT": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQLKkdD8fOZJOtuFKhK0hs5u9Jr5WmB5IiP4CEILCMcCv4N66TwIRjXLKJPnRdC-Xf2u90vvqeL2cmE/pub?gid=0&single=true&output=csv",
    "BARLEY": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQeq8k64o3LvQpnOkUv2IoYIhLO_-qJrTIvnfzwJBhsBS67m6bzzEjaYt6XMwjk0ruerIceTRVCls46/pub?gid=0&single=true&output=csv",
}


def main():
    for name, url in SHEETS.items():
        print(f"\n=== {name} ===")
        response = requests.get(url, timeout=30, headers={"User-Agent": "wagga-feed/1.0"})
        response.raise_for_status()
        print(f"HTTP {response.status_code}; {len(response.content)} bytes")
        text = response.content.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
        print(f"Rows: {len(rows)}")
        print("--- FULL SHEET ---")
        for i, row in enumerate(rows, 1):
            print(f"{i}: " + " | ".join(cell.strip() for cell in row))
        print("--- END SHEET ---")


if __name__ == "__main__":
    main()
