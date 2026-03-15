#!/usr/bin/env python3
"""
Build GeoJSON files from school CSVs.
Run after updating school_performance.csv or nces_geocodes.csv.

Usage:
    python3 scripts/build_geojson.py
"""
import csv
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")


def load_csv(path):
    with open(os.path.join(DATA, path)) as f:
        return list(csv.DictReader(f))


def main():
    geocodes = {r["state_school_id"]: r for r in load_csv("schools/nces_geocodes.csv")}
    perf = {r["state_school_id"]: r for r in load_csv("csv_exports/school_performance.csv")}
    schools = load_csv("csv_exports/school_master.csv")

    categories = {
        "elementary": [],
        "middle": [],
        "high": [],
        "magnet": [],
        "charter": [],
        "private": [],
    }

    for s in schools:
        sid = s["state_school_id"]
        geo = geocodes.get(sid)
        p = perf.get(sid, {})
        if not geo:
            continue

        props = {
            "id": sid,
            "name": s["school_name"],
            "district": s["district"],
            "county": s["county"],
            "type": s["school_type"],
            "grades_served": s.get("grades_served", ""),
            "grade": p.get("fl_school_grade", "N/A"),
            "score": float(p.get("public_zone_score", 0) or 0),
            "ela_pct": float(p.get("ela_achievement_pct", 0) or 0),
            "math_pct": float(p.get("math_achievement_pct", 0) or 0),
            "growth_pct": float(p.get("growth_pct", 0) or 0),
            "grad_pct": float(p.get("graduation_pct", 0) or 0),
            "is_charter": s.get("is_charter", "NO"),
            "is_magnet": s.get("is_magnet", ""),
            "is_private": s.get("is_private", "NO"),
        }

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(geo["longitude"]), float(geo["latitude"])],
            },
            "properties": props,
        }

        if s.get("is_private") == "YES":
            categories["private"].append(feature)
        elif s.get("is_magnet") == "YES":
            categories["magnet"].append(feature)
        elif s.get("is_charter") == "YES":
            categories["charter"].append(feature)
        elif s["school_type"] == "Elementary":
            categories["elementary"].append(feature)
        elif s["school_type"] in ("Middle/Junior",):
            categories["middle"].append(feature)
        elif s["school_type"] in ("Senior High",):
            categories["high"].append(feature)
        elif s.get("is_zoned_public") == "YES":
            categories["elementary"].append(feature)

    for name, features in categories.items():
        path = os.path.join(DATA, f"schools/{name}_schools.geojson")
        with open(path, "w") as f:
            json.dump({"type": "FeatureCollection", "features": features}, f)
        print(f"  {name}: {len(features)} schools -> {path}")

    all_feats = []
    for name, features in categories.items():
        for feat in features:
            feat["properties"]["category"] = name
            all_feats.append(feat)
    with open(os.path.join(DATA, "schools/all_schools.geojson"), "w") as f:
        json.dump({"type": "FeatureCollection", "features": all_feats}, f)
    print(f"  TOTAL: {len(all_feats)} schools")


if __name__ == "__main__":
    main()
