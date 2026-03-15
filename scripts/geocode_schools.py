#!/usr/bin/env python3
"""
Geocode schools using Mapbox Geocoding API.
Reads school_master.csv, writes/updates nces_geocodes.csv.

Usage:
    MAPBOX_TOKEN=pk.xxx python3 scripts/geocode_schools.py
"""
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

TOKEN = os.environ.get("MAPBOX_TOKEN", "")
if not TOKEN:
    print("Set MAPBOX_TOKEN environment variable")
    sys.exit(1)


def geocode_mapbox(query):
    encoded = urllib.parse.quote(query)
    url = (
        f"https://api.mapbox.com/geocoding/v5/mapbox.places/{encoded}.json"
        f"?access_token={TOKEN}&country=US&bbox=-82.5,27.0,-80.5,29.5&limit=1"
    )
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    features = data.get("features", [])
    if features:
        coords = features[0]["geometry"]["coordinates"]
        return coords[1], coords[0], features[0].get("place_name", "")
    return None, None, None


def main():
    # Load existing geocodes
    geocode_path = os.path.join(DATA, "schools/nces_geocodes.csv")
    existing = {}
    if os.path.exists(geocode_path):
        with open(geocode_path) as f:
            for row in csv.DictReader(f):
                existing[row["state_school_id"]] = row

    # Load school master
    schools = []
    with open(os.path.join(DATA, "csv_exports/school_master.csv")) as f:
        for row in csv.DictReader(f):
            schools.append(row)

    results = list(existing.values())
    new_count = 0

    for i, s in enumerate(schools):
        sid = s["state_school_id"]
        if sid in existing:
            continue

        county = s.get("county", s.get("district", ""))
        query = f"{s['school_name']}, {county} County, Florida"

        try:
            lat, lon, addr = geocode_mapbox(query)
            if lat:
                results.append({
                    "state_school_id": sid,
                    "school_name": s["school_name"],
                    "district": s.get("district", ""),
                    "county": county,
                    "school_type": s.get("school_type", ""),
                    "latitude": round(lat, 6),
                    "longitude": round(lon, 6),
                    "geocode_address": addr,
                })
                new_count += 1
                print(f"  OK: {s['school_name']}")
            else:
                print(f"  NOT FOUND: {query}")
        except Exception as e:
            print(f"  ERROR: {query} -> {e}")

        time.sleep(0.1)

    with open(geocode_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "state_school_id", "school_name", "district", "county",
                "school_type", "latitude", "longitude", "geocode_address",
            ],
        )
        writer.writeheader()
        writer.writerows(results)

    print(f"\nGeocoded {new_count} new schools. Total: {len(results)}")


if __name__ == "__main__":
    main()
