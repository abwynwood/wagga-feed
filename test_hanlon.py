import re
import requests
from urllib.parse import urljoin

PAGE_URL = "https://app.agridigital.io/community/prices?location=Hanlon+Enterprises"

KEYWORDS = re.compile(
    r"(?:api|graphql|prices?|market|grain|wheat|barley|APW1|BAR1|Hanlon|Ungarie|Junee|Riverina)",
    re.IGNORECASE,
)
URL_RE = re.compile(r'https?://[^\"\'<>\\s]+')
SCRIPT_RE = re.compile(r'<script[^>]+src=[\"\']([^\"\']+)[\"\']', re.IGNORECASE)


def fetch(session, url):
    return session.get(
        url,
        timeout=30,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/130.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )


def print_matches(label, text):
    print(f"--- {label} keyword matches ---")
    matches = []
    for match in KEYWORDS.finditer(text):
        start = max(0, match.start() - 160)
        end = min(len(text), match.end() + 240)
        snippet = re.sub(r"\s+", " ", text[start:end])
        if snippet not in matches:
            matches.append(snippet)
        if len(matches) >= 20:
            break
    if not matches:
        print("No keyword matches found")
    else:
        for snippet in matches:
            print(snippet)


def main():
    session = requests.Session()
    print("=== HANLON AGRIDIGITAL DIAGNOSTIC ===")
    print(f"Request: {PAGE_URL}")

    response = fetch(session, PAGE_URL)
    print(f"HTTP: {response.status_code}")
    print(f"Final URL: {response.url}")
    print(f"Content-Type: {response.headers.get('content-type', '')}")
    print(f"Bytes: {len(response.content)}")
    print("Headers:")
    for key in ("server", "location", "x-powered-by", "cache-control", "etag"):
        if response.headers.get(key):
            print(f"  {key}: {response.headers[key]}")

    text = response.text
    print("\n--- HTML START (first 12000 chars) ---")
    print(text[:12000])
    print("--- HTML END ---")

    scripts = []
    for src in SCRIPT_RE.findall(text):
        scripts.append(urljoin(response.url, src))
    scripts = list(dict.fromkeys(scripts))
    print(f"\nScript sources found: {len(scripts)}")
    for url in scripts:
        print(url)

    print_matches("HTML", text)

    # Inspect a limited number of frontend bundles for API/data endpoints.
    print("\n=== FRONTEND BUNDLE INSPECTION ===")
    for index, script_url in enumerate(scripts[:15], 1):
        try:
            script_response = session.get(script_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            body = script_response.text
            print(f"\n[{index}] {script_url}")
            print(f"HTTP {script_response.status_code}; {len(script_response.content)} bytes; {script_response.headers.get('content-type', '')}")

            urls = []
            for found in URL_RE.findall(body):
                clean = found.rstrip("),;]}")
                if clean not in urls:
                    urls.append(clean)
            interesting_urls = [
                u for u in urls
                if re.search(r"api|graphql|price|market|community|grain", u, re.IGNORECASE)
            ]
            if interesting_urls:
                print("Interesting URLs:")
                for u in interesting_urls[:30]:
                    print(f"  {u}")

            # Print only short, relevant snippets rather than dumping minified bundles.
            print_matches("BUNDLE", body)
        except Exception as exc:
            print(f"Bundle fetch failed: {exc}")

    print("\n=== END HANLON DIAGNOSTIC ===")


if __name__ == "__main__":
    main()
