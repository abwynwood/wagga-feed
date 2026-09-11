from cropconnect_grain import (
    TARGETS,
    as_rows,
    browser_fallback,
    fetch_all_bids,
    find_bids,
    get_json,
    normalise,
    SITE_URL,
    current_season,
)

TARGETS.clear()
TARGETS.update({
    "Nyngan BAR1": ("Nyngan", "BAR1"),
    "Griffith BAR1": ("Griffith", "BAR1"),
})

season = current_season()
print(f"BAR1 test season={season}")

response = get_json(SITE_URL, {"$top": "1000", "$format": "json"})
print(f"BAR1 test: Site API HTTP={response.status_code}")
rows = as_rows(response.json()) if response.status_code == 200 else []
site_map = {}
for row in rows:
    site_no = row.get("SiteNo") or row.get("Site") or row.get("SiteID")
    text = " ".join(str(v) for v in row.values())
    for location in ("nyngan", "griffith"):
        if normalise(location) in normalise(text) and site_no is not None:
            site_map[location] = str(site_no)
print(f"BAR1 test site map={site_map}")

bids = fetch_all_bids()
matched = find_bids(bids, site_map, season)

if not all(name in matched for name in TARGETS):
    print("BAR1 test: direct API did not find every target; running browser fallback")
    fallback = browser_fallback(season, site_map)
    matched.update({k: v for k, v in fallback.items() if k in TARGETS})

for name in TARGETS:
    value = matched.get(name)
    print(f"BAR1 TEST RESULT: {name} = {value if value is not None else 'UNAVAILABLE'}")

if not any(name in matched for name in TARGETS):
    raise SystemExit("No current BAR1 price found for either test location")
