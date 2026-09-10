import re
import requests
from urllib.parse import urljoin

PAGE_URL = "https://app.agridigital.io/community/prices?location=Hanlon+Enterprises"
SCRIPT_RE = re.compile(r'<script[^>]+src=[\"\']([^\"\']+)[\"\']', re.IGNORECASE)
ENDPOINT_RE = re.compile(r'(?:https?://[^\"\'<>\s]+|[\"\']/(?:api|graphql|community|v[0-9]+)[^\"\'<>\s]*)', re.IGNORECASE)
CONTEXT_RE = re.compile(r'(?:graphql|/api/|api\.|baseUrl|rootUrl|community/prices|priceBasis|prices|market)', re.IGNORECASE)


def get(session, url):
    return session.get(
        url,
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )


def clean(value):
    return value.rstrip("),;]}}")


def snippets(text, limit=8):
    found = []
    for match in CONTEXT_RE.finditer(text):
        start = max(0, match.start() - 220)
        end = min(len(text), match.end() + 420)
        value = re.sub(r"\s+", " ", text[start:end])
        if len(value) > 700:
            value = value[:700] + "..."
        if value not in found:
            found.append(value)
        if len(found) >= limit:
            break
    return found


def main():
    session = requests.Session()
    print("=== HANLON AGRIDIGITAL DIAGNOSTIC v2 ===")
    response = get(session, PAGE_URL)
    print(f"HTTP: {response.status_code}")
    print(f"Final URL: {response.url}")
    print(f"Content-Type: {response.headers.get('content-type', '')}")
    print(f"HTML bytes: {len(response.content)}")

    scripts = list(dict.fromkeys(urljoin(response.url, src) for src in SCRIPT_RE.findall(response.text)))
    print(f"JS bundles found: {len(scripts)}")

    endpoint_candidates = []
    bundle_summaries = []

    for index, script_url in enumerate(scripts, 1):
        try:
            r = get(session, script_url)
            body = r.text
            bundle_summaries.append((index, script_url, r.status_code, len(r.content)))
            for found in ENDPOINT_RE.findall(body):
                value = clean(found)
                if value not in endpoint_candidates:
                    endpoint_candidates.append(value)
        except Exception as exc:
            print(f"Bundle {index} failed: {exc}")

    print("\n=== BUNDLES ===")
    for index, url, status, size in bundle_summaries:
        print(f"{index}: HTTP {status}; {size} bytes; {url}")

    print("\n=== ENDPOINT CANDIDATES ===")
    if endpoint_candidates:
        for value in endpoint_candidates[:200]:
            print(value)
    else:
        print("None found")

    print("\n=== RELEVANT CODE CONTEXT ===")
    total = 0
    for index, script_url, status, size in bundle_summaries:
        if total >= 50:
            break
        try:
            body = get(session, script_url).text
            if not CONTEXT_RE.search(body):
                continue
            relevant = snippets(body, limit=min(8, 50 - total))
            if relevant:
                print(f"\n--- Bundle {index}: {script_url} ---")
                for value in relevant:
                    print(value)
                    total += 1
        except Exception:
            pass

    print("\n=== END HANLON DIAGNOSTIC ===")


if __name__ == "__main__":
    main()
