#!/usr/bin/env python3
"""
Google Pollen Report - lightweight alternative to scrape.py

Fetches point-accurate pollen data from the Google Pollen API (latitude /
longitude based, no ZIP-level averaging) plus AQI from Open-Meteo, and
renders a compact report where every value is shown as a graded index
(X/5 with a category word) instead of raw counts.

Only two data sources, no browser automation, no extra dependencies
(Python standard library only).

Data sources:
  1. Google Pollen API (forecast:lookup) - needs GOOGLE_POLLEN_API_KEY
  2. Open-Meteo Air Quality API          - no key required

Usage:
  export GOOGLE_POLLEN_API_KEY=...
  python3 google_pollen_report.py                      # default Austin 78750 point
  python3 google_pollen_report.py --lat 30.44 --lng -97.80 --label "Austin, TX"
  python3 google_pollen_report.py --json-file saved.json   # render offline

Layout notes (the reason this variant exists):
  - Tree / Grass / Weed get exactly one line each.
  - The active species of each type are listed inside that type's line,
    as "Chinese name + English name" (e.g. 榆树 Elm).
  - Species whose index equals their type's index are named only; a
    species with a different index carries its own X/5.
  - Single-character level words are padded with a full-width space
    (（低　） vs （极低）) so the three lines align vertically.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date

# ─── Defaults ─────────────────────────────────────────────────────────────────
# Spicewood Elementary School, Austin TX 78750 (same default point as scrape.py)
DEFAULT_LAT = 30.4446283
DEFAULT_LNG = -97.8039171
DEFAULT_LABEL = "Anderson Mill, Austin 78750"

GOOGLE_URL = "https://pollen.googleapis.com/v1/forecast:lookup"
OPEN_METEO_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

LEVEL_ZH = {
    "None": "无",
    "Very Low": "极低",
    "Low": "低",
    "Moderate": "中等",
    "High": "高",
    "Very High": "极高",
}

# Species code -> (pollen type, Chinese name). Google plantInfo entries do
# not carry their pollen type, so the mapping lives here. Codes not listed
# fall back to grouping by a unique matching type index (see group_species).
SPECIES = {
    # Trees
    "ALDER": ("TREE", "桤木"),
    "ASH": ("TREE", "白蜡树"),
    "BIRCH": ("TREE", "桦树"),
    "CEDAR": ("TREE", "雪松"),
    "COTTONWOOD": ("TREE", "三角叶杨"),
    "CYPRESS": ("TREE", "柏树"),
    "ELM": ("TREE", "榆树"),
    "HAZEL": ("TREE", "榛树"),
    "HICKORY": ("TREE", "山核桃树"),
    "JUNIPER": ("TREE", "杜松"),
    "MAPLE": ("TREE", "枫树"),
    "MESQUITE": ("TREE", "牧豆树"),
    "MULBERRY": ("TREE", "桑树"),
    "OAK": ("TREE", "橡树"),
    "OLIVE": ("TREE", "橄榄树"),
    "PECAN": ("TREE", "山核桃"),
    "PINE": ("TREE", "松树"),
    "POPLAR": ("TREE", "杨树"),
    "WALNUT": ("TREE", "胡桃树"),
    "WILLOW": ("TREE", "柳树"),
    # Grasses
    "GRAMINALES": ("GRASS", "禾本科"),
    # Weeds
    "AMARANTH": ("WEED", "苋"),
    "ARTEMISIA": ("WEED", "艾蒿"),
    "CHENOPODIUM": ("WEED", "藜"),
    "MUGWORT": ("WEED", "艾蒿"),
    "NETTLE": ("WEED", "荨麻"),
    "PLANTAIN": ("WEED", "车前草"),
    "RAGWEED": ("WEED", "豚草"),
    "SORREL": ("WEED", "酸模"),
}

TYPE_LINES = [
    ("TREE", "🌳", "树木"),
    ("GRASS", "🌱", "草类"),
    ("WEED", "🌾", "杂草"),
]

WEEKDAYS_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def fetch_json(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_google(lat, lng, days, api_key):
    return fetch_json(
        GOOGLE_URL,
        {
            "location.latitude": lat,
            "location.longitude": lng,
            "days": days,
            "languageCode": "en-US",
            "key": api_key,
        },
    )


def fetch_aqi(lat, lng):
    """Return (current AQI, daily max AQI, current PM2.5) from Open-Meteo."""
    data = fetch_json(
        OPEN_METEO_URL,
        {
            "latitude": lat,
            "longitude": lng,
            "hourly": "us_aqi,pm2_5",
            "forecast_days": 1,
            "timezone": "America/Chicago",
        },
    )
    hourly = data.get("hourly", {})
    aqi = [v for v in hourly.get("us_aqi", []) if v is not None]
    pm = [v for v in hourly.get("pm2_5", []) if v is not None]
    if not aqi:
        return None
    # "Current" = the hour closest to now in the payload's own timeline;
    # the API returns local-time hours starting at midnight.
    times = hourly.get("time", [])
    from datetime import datetime

    now = datetime.now()
    idx = 0
    for i, t in enumerate(times):
        try:
            if datetime.fromisoformat(t) <= now:
                idx = i
        except ValueError:
            pass
    current_pm = pm[idx] if idx < len(pm) else (pm[0] if pm else None)
    return aqi[idx], max(aqi), current_pm


def aqi_category(aqi):
    if aqi <= 50:
        return "良好"
    if aqi <= 100:
        return "中等"
    if aqi <= 150:
        return "对敏感人群不健康"
    if aqi <= 200:
        return "不健康"
    if aqi <= 300:
        return "非常不健康"
    return "危险"


def level_text(index_info):
    """'2/5（低　）' - single-char levels padded with a full-width space."""
    if not index_info:
        return "无数据"
    value = index_info.get("value", 0)
    zh = LEVEL_ZH.get(index_info.get("category", ""), index_info.get("category", ""))
    if len(zh) == 1:
        zh += "　"
    return f"{value}/5（{zh}）"


def group_species(day):
    """Map TREE/GRASS/WEED -> [(zh name, english name, value)] with value > 0."""
    types = {
        t["code"]: (t.get("indexInfo") or {})
        for t in day.get("pollenTypeInfo", [])
    }
    grouped = {code: [] for code, _, _ in TYPE_LINES}
    for plant in day.get("plantInfo", []):
        info = plant.get("indexInfo") or {}
        value = info.get("value")
        if not value:
            continue
        code = plant.get("code", "")
        english = plant.get("displayName", code)
        if code in SPECIES:
            ptype, zh = SPECIES[code]
        else:
            # Unknown code: group under the single type whose index matches.
            matches = [c for c, ii in types.items() if ii.get("value") == value]
            ptype = matches[0] if len(matches) == 1 else None
            zh = english
        if ptype in grouped:
            grouped[ptype].append((zh, english, value))
    for items in grouped.values():
        items.sort(key=lambda x: -x[2])
    return grouped


def render(google_data, aqi, label):
    days = google_data.get("dailyInfo", [])
    if not days:
        return "Google Pollen 返回了空数据。"
    today = days[0]
    d = today.get("date", {})
    day_date = date(d.get("year", 1970), d.get("month", 1), d.get("day", 1))
    grouped = group_species(today)
    types = {
        t["code"]: (t.get("indexInfo") or {})
        for t in today.get("pollenTypeInfo", [])
    }

    out = []
    out.append("🌿 花粉报告")
    out.append(f"📍 {label}")
    out.append(
        f"🗓️ {day_date.year}年{day_date.month}月{day_date.day}日"
        f"（{WEEKDAYS_ZH[day_date.weekday()]}）"
    )
    out.append("")
    out.append("今日花粉")
    max_today = 0
    for code, emoji, zh_label in TYPE_LINES:
        info = types.get(code) or {}
        if info.get("value") is not None:
            max_today = max(max_today, info["value"])
        species_bits = []
        for zh_name, english, value in grouped.get(code, []):
            bit = f"{zh_name} {english}" if zh_name != english else english
            if value != info.get("value"):
                species_bits.append(f"{bit} {value}/5")
            else:
                species_bits.append(bit)
        species_text = "、".join(species_bits) if species_bits else "无活跃物种"
        out.append(f"{emoji} {zh_label} {level_text(info)}｜{species_text}")
    out.append("")
    out.append("🌬️ 空气质量")
    if aqi:
        current, day_max, pm = aqi
        line = f"AQI {current}/500（{aqi_category(current)}），全天最高 {day_max}"
        if pm is not None:
            line += f"，PM2.5 {pm:.1f} µg/m³"
        out.append(line)
    else:
        out.append("AQI 数据暂不可用")
    out.append("")
    out.append("未来4天")
    for day in days[1:5]:
        dd = day.get("date", {})
        fdate = date(dd.get("year", 1970), dd.get("month", 1), dd.get("day", 1))
        ftypes = {
            t["code"]: (t.get("indexInfo") or {})
            for t in day.get("pollenTypeInfo", [])
        }
        best_code, best_val = None, -1
        for code, _, _ in TYPE_LINES:
            v = (ftypes.get(code) or {}).get("value")
            if v is not None and v > best_val:
                best_code, best_val = code, v
        if best_code is None:
            out.append(f"{fdate.month:02d}/{fdate.day:02d}（{WEEKDAYS_ZH[fdate.weekday()]}）无数据")
            continue
        zh_label = dict((c, z) for c, _, z in TYPE_LINES)[best_code]
        out.append(
            f"{fdate.month:02d}/{fdate.day:02d}（{WEEKDAYS_ZH[fdate.weekday()]}）"
            f"最高 {level_text(ftypes[best_code])}，主要 {zh_label}"
        )
    out.append("")
    tips = {
        0: "💡 今天花粉极低，放心出门。",
        1: "💡 今天花粉很低，适合户外活动。",
        2: "💡 今天花粉偏低，适合户外活动；高度敏感的话回家洗手洗脸即可。",
        3: "💡 今天花粉中等，敏感的话出门戴口罩，回家换衣服洗脸。",
        4: "💡 今天花粉高，尽量减少长时间户外活动，出门戴好口罩。",
        5: "💡 今天花粉极高，尽量待在室内，关好窗户。",
    }
    out.append(tips.get(max_today, tips[2]))
    out.append("来源：Google Pollen（GPS 点位）+ Open-Meteo（AQI）")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description="Google Pollen point report")
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT)
    parser.add_argument("--lng", type=float, default=DEFAULT_LNG)
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument(
        "--json-file",
        help="Render from a saved Google Pollen API response instead of fetching",
    )
    args = parser.parse_args()

    if args.json_file:
        with open(args.json_file, encoding="utf-8") as f:
            google_data = json.load(f)
    else:
        api_key = os.environ.get("GOOGLE_POLLEN_API_KEY", "").strip()
        if not api_key:
            print(
                "GOOGLE_POLLEN_API_KEY is not set. Get a key with the "
                "Pollen API enabled and export it first.",
                file=sys.stderr,
            )
            return 1
        google_data = fetch_google(args.lat, args.lng, args.days, api_key)

    try:
        aqi = fetch_aqi(args.lat, args.lng)
    except Exception:
        aqi = None
    print(render(google_data, aqi, args.label))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
