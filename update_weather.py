#!/usr/bin/env python3
import html
import math
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

LAT = -32.5215
LON = 145.9944
LOCATION_NAME = "Wynwood NSW"
TIMEZONE = ZoneInfo("Australia/Sydney")

API_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
OUTPUT_FILE = Path(__file__).with_name("weather.xml")
USER_AGENT = "wagga-feed-weather/1.0 (+https://github.com/abwynwood/wagga-feed)"

SYMBOL_EMOJI = {
    "clearsky": "☀️",
    "fair": "🌤️",
    "partlycloudy": "⛅",
    "cloudy": "☁️",
    "fog": "🌫️",
    "lightrainshowers": "🌦️",
    "rainshowers": "🌦️",
    "heavyrainshowers": "🌧️",
    "lightrain": "🌦️",
    "rain": "🌧️",
    "heavyrain": "🌧️",
    "lightsleet": "🌨️",
    "sleet": "🌨️",
    "heavysleet": "🌨️",
    "lightsnow": "🌨️",
    "snow": "❄️",
    "heavysnow": "❄️",
    "thunderstorm": "⛈️",
}


def fetch_forecast():
    response = requests.get(
        API_URL,
        params={"lat": LAT, "lon": LON},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def local_datetime(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TIMEZONE)


def symbol_emoji(symbol_code):
    if not symbol_code:
        return "•"
    base = symbol_code.removesuffix("_day").removesuffix("_night")
    for key, emoji in SYMBOL_EMOJI.items():
        if base == key or base.startswith(key):
            return emoji
    return "•"


def wind_arrow(degrees):
    if degrees is None:
        return "→"
    directions = ["↓", "↙", "←", "↖", "↑", "↗", "→", "↘"]
    index = int((degrees + 22.5) // 45) % 8
    return directions[index]


def kmh(mps):
    return round(float(mps) * 3.6)


def build_days(forecast):
    timeseries = forecast["properties"]["timeseries"]
    today = datetime.now(TIMEZONE).date()
    dates = [today + timedelta(days=i) for i in range(10)]

    days = {
        d: {
            "temps": [],
            "wind_candidates": [],
            "rain": 0.0,
            "rain_found": False,
            "symbol_candidates": [],
        }
        for d in dates
    }

    for item in timeseries:
        local = local_datetime(item["time"])
        day = local.date()
        if day not in days:
            continue

        details = item.get("data", {}).get("instant", {}).get("details", {})
        if "air_temperature" in details:
            days[day]["temps"].append(float(details["air_temperature"]))

        if "wind_speed" in details and "wind_from_direction" in details:
            days[day]["wind_candidates"].append(
                (
                    abs((local.hour + local.minute / 60) - 15),
                    float(details["wind_speed"]),
                    float(details["wind_from_direction"]),
                )
            )

        data = item.get("data", {})

        # Prefer the period with the longest available precipitation interval
        # at each timestamp so precipitation is never double-counted.
        period = None
        # Use the 1-hour amount whenever it is available. Only fall back to
        # a 6-hour amount when the API has moved to its coarser time steps.
        for key in ("next_1_hours", "next_6_hours"):
            candidate = data.get(key)
            if candidate and "precipitation_amount" in candidate.get("details", {}):
                period = candidate
                break

        if period:
            amount = float(period["details"]["precipitation_amount"])
            days[day]["rain"] += max(0.0, amount)
            days[day]["rain_found"] = True

        # Weather symbols describe a period rather than an instant. Keep the
        # symbol closest to local midday for the compact daily display.
        for key in ("next_6_hours", "next_1_hours", "next_12_hours"):
            candidate = data.get(key)
            code = candidate.get("summary", {}).get("symbol_code") if candidate else None
            if code:
                distance = abs((local.hour + local.minute / 60) - 12)
                days[day]["symbol_candidates"].append((distance, code))
                break

    result = []
    for d in dates:
        info = days[d]
        temps = info["temps"]

        if not temps:
            continue

        wind = min(info["wind_candidates"], default=None)
        symbol = min(info["symbol_candidates"], default=None)

        result.append(
            {
                "date": d,
                "day": d.strftime("%a").upper(),
                "date_number": d.day,
                "symbol": symbol_emoji(symbol[1] if symbol else None),
                "rain": round(info["rain"], 1) if info["rain_found"] else None,
                "wind_speed": kmh(wind[1]) if wind else None,
                "wind_direction": wind_arrow(wind[2]) if wind else "→",
                "high": math.ceil(max(temps)),
                "low": math.floor(min(temps)),
            }
        )

    return result


def format_rain(value):
    if value is None:
        return "—"
    if value == 0:
        return "0 mm"
    return f"{value:g} mm"


def make_description(days):
    cells = []
    for item in days:
        cells.append(
            "<td style=\"width:10%;text-align:center;padding:4px 2px;vertical-align:top;white-space:nowrap;\">"
            f"<strong>{item['day']} {item['date_number']}</strong><br>"
            f"<span style=\"font-size:28px;\">{item['symbol']}</span><br>"
            f"{format_rain(item['rain'])}<br>"
            f"{item['wind_direction']} {item['wind_speed']} km/h<br>"
            f"{item['high']}° / {item['low']}°"
            "</td>"
        )

    while len(cells) < 10:
        cells.append("<td style=\"width:10%;\"></td>")

    return (
        "<div style=\"width:100%;overflow:hidden;\">"
        "<div style=\"text-align:center;font-weight:bold;margin-bottom:6px;\">"
        f"10-DAY FORECAST — {html.escape(LOCATION_NAME.upper())}"
        "</div>"
        "<table style=\"width:100%;table-layout:fixed;border-collapse:collapse;\"><tr>"
        + "".join(cells)
        + "</tr></table>"
        "<div style=\"text-align:right;font-size:10px;margin-top:4px;\">"
        "Forecast: MET Norway"
        "</div>"
        "</div>"
    )


def write_xml(days):
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    description = make_description(days)

    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>10-Day Weather Forecast — {html.escape(LOCATION_NAME)}</title>
    <link>{API_URL}</link>
    <description><![CDATA[{description}]]></description>
    <language>en-au</language>
    <item>
      <title>10-Day Forecast — {html.escape(LOCATION_NAME)}</title>
      <link>{API_URL}</link>
      <guid>weather-forecast-{LAT}-{LON}</guid>
      <pubDate>{now}</pubDate>
      <description><![CDATA[{description}]]></description>
    </item>
  </channel>
</rss>
'''
    OUTPUT_FILE.write_text(xml, encoding="utf-8")


def main():
    forecast = fetch_forecast()
    days = build_days(forecast)
    if len(days) < 10:
        raise RuntimeError(
            f"MET Norway returned only {len(days)} local forecast days; refusing to publish a partial strip."
        )
    write_xml(days)
    print(f"Wrote {OUTPUT_FILE} for {LOCATION_NAME} ({LAT}, {LON})")
    for item in days:
        print(
            f"{item['day']} {item['date_number']}: "
            f"{item['symbol']} {format_rain(item['rain'])}, "
            f"{item['wind_direction']} {item['wind_speed']} km/h, "
            f"{item['high']}°/{item['low']}°"
        )


if __name__ == "__main__":
    main()
