#!/usr/bin/env python3
"""
Replace old SABS Polk County boundaries with current data from
Polk County Schools ArcGIS FeatureServer.
"""
import json
import os
import re
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
BOUNDS = os.path.join(DATA, "boundaries")

URLS = {
    "elementary": "https://services1.arcgis.com/eQkYxfzo5tjzR0Oj/arcgis/rest/services/Elementary_Zones_asof_8MAY2024/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson&resultOffset=0&resultRecordCount=200",
    "middle": "https://services1.arcgis.com/eQkYxfzo5tjzR0Oj/arcgis/rest/services/Middle_School_Zones_2025_2026/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson&resultOffset=0&resultRecordCount=200",
    "high": "https://services1.arcgis.com/eQkYxfzo5tjzR0Oj/arcgis/rest/services/High_School_Zones_25_26SY/FeatureServer/4/query?where=1%3D1&outFields=*&f=geojson&resultOffset=0&resultRecordCount=200",
}

GRADE_BANDS = {
    "elementary": "Elementary",
    "middle": "Middle",
    "high": "High",
}

ZONE_FILES = {
    "elementary": os.path.join(BOUNDS, "elementary_zones.geojson"),
    "middle": os.path.join(BOUNDS, "middle_zones.geojson"),
    "high": os.path.join(BOUNDS, "high_zones.geojson"),
}

# Manual name mappings: ArcGIS name (upper) -> SCHOOLS name (upper)
MANUAL_MAP = {
    "JESSE KEENE ELEMENTARY": "JESSE KEEN ELEMENTARY SCHOOL",
    "FROSTBEN HILL GRIFFIN JR. ELEM": "BEN HILL GRIFFIN JR ELEMENTARY SCHOOL",  # weird concat
    "FROSTPROOF MIDDLE/SR": "FROSTPROOF MIDDLE/SENIOR HIGH",
    "FT MEADE MIDDLE/SR": "FORT MEADE MIDDLE/SENIOR HIGH SCHOOL",
    "SHELLY S. BOONE MIDDLE": "SHELLEY S. BOONE MIDDLE SCHOOL",
    "DENSION MIDDLE": "DENISON MIDDLE SCHOOL",
    "BELLA CITA K-8": "BELLA CITTA",
    "CITRUS RIDGE K-8": "CITRUS RIDGE A CIVICS ACADEMY",
    "MCLAUGHLIN ACADEMY OF EXCELLENCE": "MCLAUGHLIN MIDDLE SCHOOL AND FINE ARTS ACADEMY",
    "NORTH LAKELAND ELEMENTARY SCHO": "NORTH LAKELAND ELEMENTARY SCHOOL OF CHOICE",
    "EDGAR PADGETT ELEMENTARY": "EDGAR L. PADGETT ELEMENTARY",
    "PHILLIP O'BRIEN ELEMENTARY": "PHILIP O'BRIEN ELEMENTARY SCHOOL",
    "JAMES SIKES ELEMENTARY": "JAMES W. SIKES ELEMENTARY SCHOOL",
    "JL STAMBAUGH MIDDLE": "JERE L. STAMBAUGH MIDDLE",
    "GEORGE JENKINS SENIOR HIGH": "GEORGE W. JENKINS SENIOR HIGH",
}


def load_schools_lookup():
    """Load school performance data from index.html line 98."""
    html_path = os.path.join(BASE, "index.html")
    with open(html_path) as f:
        for i, line in enumerate(f, 1):
            if i == 98:
                js = line.strip().rstrip(";")
                js = js[len("const SCHOOLS = "):]
                schools = json.loads(js)
                break

    lookup = {}
    for cat, fc in schools.items():
        for feat in fc["features"]:
            p = feat["properties"]
            if p.get("district") == "POLK":
                lookup[p["name"].upper().strip()] = p
    return lookup


def normalize(name):
    """Strip common suffixes for fuzzy matching."""
    n = name.upper().strip()
    for suffix in [
        " ELEMENTARY SCHOOL", " ELEMENTARY", " MIDDLE SCHOOL",
        " SENIOR HIGH SCHOOL", " SENIOR HIGH", " HIGH SCHOOL",
        " MIDDLE", " HIGH", " K-8", " SCHOOL",
    ]:
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
    # Remove punctuation
    n = re.sub(r"[.\-']", "", n)
    return n.strip()


def match_school(zone_name, lookup):
    """Try to match a zone name to a school in the lookup."""
    zu = zone_name.upper().strip()

    # Check manual mapping first
    if zu in MANUAL_MAP:
        mapped = MANUAL_MAP[zu]
        if mapped in lookup:
            return lookup[mapped]

    # Exact match
    if zu in lookup:
        return lookup[zu]

    # Try with common suffixes added
    for suffix in [" ELEMENTARY SCHOOL", " MIDDLE SCHOOL", " SENIOR HIGH SCHOOL", " HIGH SCHOOL", " SCHOOL"]:
        candidate = zu + suffix
        if candidate in lookup:
            return lookup[candidate]

    # Normalized match
    zn = normalize(zu)
    for name, props in lookup.items():
        if normalize(name) == zn:
            return props

    # Contains match
    for name, props in lookup.items():
        nn = normalize(name)
        if zn and nn and (zn in nn or nn in zn):
            return props

    return None


def download_zones(level):
    """Download zone GeoJSON from ArcGIS."""
    url = URLS[level]
    print(f"  Downloading {level} zones...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
    return data


def process_zones(level, raw_geojson, lookup):
    """Convert ArcGIS features to our format, matching to school data."""
    features = []
    matched = 0
    unmatched = 0
    skipped = 0

    for feat in raw_geojson.get("features", []):
        props = feat.get("properties", {})
        zone_name = props.get("SchoolName", "") or ""
        if not zone_name.strip():
            skipped += 1
            continue

        school = match_school(zone_name, lookup)
        if school:
            matched += 1
            new_props = {
                "zone_name": zone_name,
                "district": "POLK",
                "grade_band": GRADE_BANDS[level],
                "grade": school.get("grade", "N/A"),
                "score": school.get("score", 0),
                "school_name": school["name"],
                "ela_pct": school.get("ela_pct", 0),
                "math_pct": school.get("math_pct", 0),
            }
        else:
            unmatched += 1
            new_props = {
                "zone_name": zone_name,
                "district": "POLK",
                "grade_band": GRADE_BANDS[level],
                "grade": "N/A",
                "score": 0,
                "school_name": zone_name.upper(),
                "ela_pct": 0,
                "math_pct": 0,
            }
            print(f"    UNMATCHED: {zone_name}")

        new_feat = {
            "type": "Feature",
            "geometry": feat["geometry"],
            "properties": new_props,
        }
        features.append(new_feat)

    print(f"  {level}: {matched} matched, {unmatched} unmatched, {skipped} skipped (empty name)")
    return features


def update_zone_file(level, new_polk_features):
    """Replace Polk features in the zone GeoJSON file."""
    path = ZONE_FILES[level]
    with open(path) as f:
        data = json.load(f)

    # Remove old Polk features
    old_count = len([f for f in data["features"] if f["properties"].get("district") == "POLK"])
    data["features"] = [f for f in data["features"] if f["properties"].get("district") != "POLK"]
    data["features"].extend(new_polk_features)

    with open(path, "w") as f:
        json.dump(data, f)

    print(f"  {level}: replaced {old_count} old Polk zones with {len(new_polk_features)} new zones")


def update_index_html():
    """Rebuild the BOUNDARIES line in index.html from updated zone files."""
    boundaries = {}
    for level in ("elementary", "middle", "high"):
        with open(ZONE_FILES[level]) as f:
            boundaries[level] = json.load(f)

    html_path = os.path.join(BASE, "index.html")
    with open(html_path) as f:
        lines = f.readlines()

    # Line 99 (0-indexed: 98) contains the BOUNDARIES
    boundaries_json = json.dumps(boundaries, separators=(",", ":"))
    lines[98] = f"const BOUNDARIES = {boundaries_json};\n"

    with open(html_path, "w") as f:
        f.writelines(lines)

    print("  Updated index.html BOUNDARIES inline data")


def main():
    print("Loading school performance data...")
    lookup = load_schools_lookup()
    print(f"  Found {len(lookup)} Polk County schools\n")

    all_new = {}
    for level in ("elementary", "middle", "high"):
        print(f"Processing {level}...")
        raw = download_zones(level)
        new_features = process_zones(level, raw, lookup)
        all_new[level] = new_features
        update_zone_file(level, new_features)
        print()

    print("Updating index.html...")
    update_index_html()

    # Verify
    print("\nVerification - Davenport/Haines City zones:")
    for level, features in all_new.items():
        for f in features:
            name = f["properties"]["zone_name"]
            if any(kw in name.upper() for kw in ["DAVEN", "HAINES", "BELLA", "CITRUS RIDGE"]):
                grade = f["properties"]["grade"]
                print(f"  {level}: {name} (grade: {grade})")

    print("\nDone!")


if __name__ == "__main__":
    main()
