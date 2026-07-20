#!/usr/bin/env python3
"""
geocode_zip.py — Convert ZIP code to latitude/longitude.

Uses the free US Census Bureau geocoder (no API key required).
Falls back to a small built-in lookup table for common Austin ZIPs.
"""
import sys
import json
import urllib.request
import urllib.parse

# Built-in fallback for the Austin 78750 area — keeps the dashboard working
# even when offline. Census API is preferred for accuracy.
BUILTIN_ZIPS = {
    "78750": (30.5490, -97.7805),  # Anderson Mill / 78750
    "78717": (30.4949, -97.7701),  # Avery Ranch
    "78726": (30.5446, -97.8257),  # Four Points
    "78759": (30.4152, -97.7512),  # Great Hills
    "78729": (30.4551, -97.7704),  # McNeil
    "78758": (30.3847, -97.7111),  # North Lamar
    "78613": (30.5083, -97.8203),  # Cedar Park
    "78664": (30.5083, -97.8203),  # Round Rock
    "78681": (30.5083, -97.8203),  # Round Rock
    "78704": (30.2436, -97.7682),  # South Austin
}


def geocode_zip(zip_code: str) -> tuple[float, float]:
    """Return (lat, lng) for a US ZIP code. Uses Census API, falls back to builtin."""
    if zip_code in BUILTIN_ZIPS:
        return BUILTIN_ZIPS[zip_code]

    url = (
        "https://geocoding.geo.census.gov/geocoder/"
        f"geographies/address?street=&city=&state=&zip={urllib.parse.quote(zip_code)}"
        "&benchmark=Public_AR_Current&vintage=Current_Current&format=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "tennis-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read())

    matches = payload.get("result", {}).get("addressMatches", [])
    if not matches:
        raise ValueError(f"ZIP {zip_code} not found by Census geocoder")

    coords = matches[0]["coordinates"]
    return float(coords["y"]), float(coords["x"])


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: geocode_zip.py <ZIP>", file=sys.stderr)
        return 2
    try:
        lat, lng = geocode_zip(sys.argv[1])
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"zip": sys.argv[1], "lat": lat, "lng": lng}))
    return 0


if __name__ == "__main__":
    sys.exit(main())