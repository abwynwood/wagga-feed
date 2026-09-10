import re
import requests
from urllib.parse import urljoin

PAGE_URL = "https://app.agridigital.io/community/prices?location=Hanlon+Enterprises"
API_BASE = "https://api.agridigital.io"
SCRIPT_RE = re.compile(r'<script[^>]+src=[\"\']([^\"\']+)[\"\']', re.IGNORECASE)


def get(session, url):
    return session.get(
        url,
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Origin": "https://app.agridigital.io",
            "Referer": PAGE_URL,
        },
    )


def compact(value, limit=1200):
    value = re.sub(r"\s+", " ", value)
    return value if len(value) <= limit else value[:limit] + "..."


def main():
    session = requests.Session()
    print("=== HANLON AGRIDIGITAL CASHPRICES PROBE v3 ===")

    page = get(session, PAGE_URL)
    print(f"PAGE HTTP: {page.status_code}; bytes={len(page.content)}; final={page.url}")

    scripts = list(dict.fromkeys(urljoin(page.url, src) for src in SCRIPT_RE.findall(page.text)))
    print(f"JS bundles found: {len(scripts)}")

    # Look specifically for code around cashPrices, relatedEndpoints and API URL construction.
    hits = []
    endpoint_strings = set()
    for index, script_url in enumerate(scripts, 1):
        try:
            r = get(session, script_url)
            body = r.text
            for token in ("cashPrices", "relatedEndpoints", "api.agridigital.io", "baseUrl", "community/prices"):
                pos = 0
                while True:
                    pos = body.find(token, pos)
                    if pos < 0:
                        break
                    start = max(0, pos - 700)
                    end = min(len(body), pos + 1400)
                    snippet = compact(body[start:end])
                    hits.append((index, token, snippet))
                    for match in re.findall(r"(?:https?://[^\"'`\s<>]+|/[^\"'`\s<>]{1,180})", body[start:end]):
                        if any(x in match.lower() for x in ("cash", "price", "api", "community")):
                            endpoint_strings.add(match.rstrip("),;]"))
                    pos += len(token)
        except Exception as exc:
            print(f"Bundle {index} failed: {exc}")

    print("\n=== ENDPOINT-LIKE STRINGS NEAR CASH PRICE CODE ===")
    for value in sorted(endpoint_strings):
        print(value)

    print("\n=== CASH PRICE CODE CONTEXT ===")
    seen = set()
    for index, token, snippet in hits:
        key = (index, snippet)
        if key in seen:
            continue
        seen.add(key)
        print(f"\n--- bundle {index}; token={token} ---\n{snippet}")
        if len(seen) >= 30:
            break

    # Test the most likely public endpoint forms. These are deliberately probes only;
    # we do not alter the Dakboard feeds unless a response proves to contain live prices.
    candidates = [
        "/cashPrices",
        "/api/cashPrices",
        "/v1/cashPrices",
        "/v2/cashPrices",
        "/community/cashPrices",
        "/api/community/cashPrices",
        "/v1/community/cashPrices",
        "/v2/community/cashPrices",
    ]

    print("\n=== DIRECT CASHPRICES PROBES ===")
    for path in candidates:
        url = API_BASE + path
        try:
            r = get(session, url)
            ctype = r.headers.get("content-type", "")
            print(f"{path}: HTTP {r.status_code}; type={ctype}; bytes={len(r.content)}")
            print(compact(r.text, 900))
        except Exception as exc:
            print(f"{path}: ERROR {exc}")

    print("\n=== END HANLON CASHPRICES PROBE ===")


if __name__ == "__main__":
    main()
