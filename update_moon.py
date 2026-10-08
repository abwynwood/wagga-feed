#!/usr/bin/env python3
import html
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import ephem

TIMEZONE = ZoneInfo("Australia/Sydney")
OUTPUT_FILE = Path(__file__).with_name("moon.xml")
LAT = "-32.5215"
LON = "145.9944"
LOCATION_NAME = "Wynwood NSW"

PHASES = [
    ("New Moon", "🌑"),
    ("First Quarter", "🌓"),
    ("Full Moon", "🌕"),
    ("Last Quarter", "🌗"),
]


def local_date(value):
    return value.datetime().astimezone(TIMEZONE).date()


def phase_events(observer):
    events = []
    now = ephem.now()

    prev = ephem.previous_new_moon(now)
    nxt = ephem.next_new_moon(now)
    events.extend([("New Moon", prev), ("New Moon", nxt)])

    prev = ephem.previous_first_quarter_moon(now)
    nxt = ephem.next_first_quarter_moon(now)
    events.extend([("First Quarter", prev), ("First Quarter", nxt)])

    prev = ephem.previous_full_moon(now)
    nxt = ephem.next_full_moon(now)
    events.extend([("Full Moon", prev), ("Full Moon", nxt)])

    prev = ephem.previous_last_quarter_moon(now)
    nxt = ephem.next_last_quarter_moon(now)
    events.extend([("Last Quarter", prev), ("Last Quarter", nxt)])

    return events


def phase_for_today(observer):
    today = datetime.now(TIMEZONE).date()
    for name, event in phase_events(observer):
        if local_date(event) == today:
            emoji = dict(PHASES)[name]
            return name, emoji
    return None, None


def phase_name(illumination, waxing, today_phase):
    # Principal phase names are reserved for the actual local calendar date
    # containing the astronomical event. This keeps Full/New Moon to one
    # night while still showing the true illumination percentage.
    if today_phase:
        return today_phase

    if illumination < 1:
        return "New Moon"
    if illumination < 50:
        return "Waxing Crescent" if waxing else "Waning Crescent"
    if illumination < 51:
        return "First Quarter" if waxing else "Last Quarter"
    return "Waxing Gibbous" if waxing else "Waning Gibbous"


def make_description(moon):
    return (
        '<div style="width:100%;text-align:center;padding-top:24px;">'
        '<br><br>'
        f'<span style="font-size:56px;">{moon["emoji"]}</span><br>'
        f'<strong style="font-size:24px;">{moon["illumination"]}%</strong> '
        f'<strong style="font-size:20px;">{html.escape(moon["phase"])}</strong>'
        '</div>'
    )


def write_xml(moon):
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    description = make_description(moon)
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title> </title>
    <link>https://github.com/abwynwood/wagga-feed</link>
    <description><![CDATA[{description}]]></description>
    <language>en-au</language>
    <item>
      <title> </title>
      <link>https://github.com/abwynwood/wagga-feed</link>
      <guid>moon-{LAT}-{LON}</guid>
      <pubDate>{now}</pubDate>
      <description><![CDATA[{description}]]></description>
    </item>
  </channel>
</rss>
'''
    OUTPUT_FILE.write_text(xml, encoding="utf-8")


def main():
    observer = ephem.Observer()
    observer.lat = LAT
    observer.lon = LON
    observer.date = ephem.now()

    moon = ephem.Moon(observer)
    illumination = round(float(moon.phase))
    today_phase, today_emoji = phase_for_today(observer)

    # PyEphem's illuminated fraction is independent of the phase label.
    # Determine waxing/waning by comparing the illuminated percentage one day
    # into the future. This avoids relying on a tiny instantaneous difference.
    now = ephem.now()
    future_observer = ephem.Observer()
    future_observer.lat = LAT
    future_observer.lon = LON
    future_observer.date = ephem.Date(now + 1)
    future_moon = ephem.Moon(future_observer)
    waxing = float(future_moon.phase) > float(moon.phase)

    if today_phase:
        phase = today_phase
        emoji = today_emoji
    elif illumination < 50:
        phase = "Waxing Crescent" if waxing else "Waning Crescent"
        emoji = "🌒" if waxing else "🌘"
    else:
        phase = "Waxing Gibbous" if waxing else "Waning Gibbous"
        emoji = "🌔" if waxing else "🌖"

    result = {"illumination": illumination, "phase": phase, "emoji": emoji}
    write_xml(result)
    print(f'{result["emoji"]} {result["illumination"]}% — {result["phase"]}')


if __name__ == "__main__":
    main()
