#!/usr/bin/env python3
"""
Add Orange County Public Schools (OCPS) to the Orlando metro school zone map.

Steps:
  1. Extract Orange County schools from FLDOE 2025 grades Excel file
  2. Append to FDOE_Grades_2025_Raw.csv, school_master.csv, school_performance.csv
  3. Download attendance zone boundaries from OCPS ArcGIS FeatureServer
  4. Match zones to school performance data
  5. Merge into elementary/middle/high_zones.geojson
  6. Rebuild SCHOOLS and BOUNDARIES inline data in index.html
"""
import csv
import json
import os
import re
import urllib.request

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl required. Install with: pip3 install openpyxl")
    raise SystemExit(1)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
BOUNDS = os.path.join(DATA, "boundaries")
CSV_DIR = os.path.join(DATA, "csv_exports")

# OCPS ArcGIS FeatureServer for 2025-26 attendance zones
ZONE_URL = (
    "https://services1.arcgis.com/OIHmIXKmWvkweUZp/arcgis/rest/services/"
    "Find_My_School_2526_Online/FeatureServer/1/query"
)

# FLDOE source
FLDOE_URL = "https://www.fldoe.org/file/18534/SchoolGrades25.xlsx"
FLDOE_LOCAL = os.path.join(DATA, "FLDOE_SchoolGrades25.xlsx")

# School type codes from FLDOE
TYPE_MAP = {
    "01": "Elementary",
    "02": "Middle/Junior",
    "03": "Senior High",
    "04": "Combination",
}

GRADE_MAP = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}

ZONE_FILES = {
    "elementary": os.path.join(BOUNDS, "elementary_zones.geojson"),
    "middle": os.path.join(BOUNDS, "middle_zones.geojson"),
    "high": os.path.join(BOUNDS, "high_zones.geojson"),
}

# ArcGIS TYPE field -> our grade_band
ARCGIS_TYPE_MAP = {
    "ES": "Elementary",
    "MS": "Middle",
    "HS": "High",
    "K8": "Elementary",  # K-8 zones go into elementary
    "PS8": "Elementary",  # PreK-8 zones go into elementary
}

# Which zone file each ArcGIS TYPE maps to
ARCGIS_TYPE_FILE = {
    "ES": "elementary",
    "MS": "middle",
    "HS": "high",
    "K8": "elementary",
    "PS8": "elementary",
}

# Manual name mappings: ArcGIS zone name (upper) -> FLDOE school name (upper)
# Add entries here if fuzzy matching fails
MANUAL_MAP = {
    "LAKE COMO": "LAKE COMO SCHOOL",
    "OCPS ACE": "OCPS ACADEMIC CENTER FOR EXCELLENCE",
    "DR PHILLIPS": "DR. PHILLIPS HIGH SCHOOL",
    "WEST OAKS": "WEST OAKS MIDDLE SCHOOL",
    "MEADOW WOODS": "MEADOW WOODS MIDDLE SCHOOL",
    "JONES": "JONES HIGH SCHOOL",
    "OAK RIDGE": "OAK RIDGE HIGH SCHOOL",
    "EVANS": "EVANS HIGH SCHOOL",
    "EDGEWATER": "EDGEWATER HIGH SCHOOL",
    "COLONIAL": "COLONIAL HIGH SCHOOL",
    "BOONE": "BOONE HIGH SCHOOL",
    "WEKIVA": "WEKIVA HIGH SCHOOL",
    "TIMBER CREEK": "TIMBER CREEK HIGH SCHOOL",
    "OLYMPIA": "OLYMPIA HIGH SCHOOL",
    "WINDERMERE": "WINDERMERE HIGH SCHOOL",
    "FREEDOM": "FREEDOM HIGH SCHOOL",
    "UNIVERSITY": "UNIVERSITY HIGH SCHOOL",
    "EAST RIVER": "EAST RIVER HIGH SCHOOL",
    "OCOEE": "OCOEE HIGH SCHOOL",
    "WEST ORANGE": "WEST ORANGE HIGH SCHOOL",
    "APOPKA": "APOPKA HIGH SCHOOL",
}


def safe_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def calc_score(grade_letter, ela, math, ela_gains, math_gains, grad, career):
    grade_pts = GRADE_MAP.get(grade_letter, 0)
    grade_norm = (grade_pts / 4.0) * 100.0
    gains_count = 0
    gains_sum = 0.0
    if ela_gains > 0:
        gains_sum += ela_gains
        gains_count += 1
    if math_gains > 0:
        gains_sum += math_gains
        gains_count += 1
    growth = gains_sum / gains_count if gains_count > 0 else 0.0
    score = (
        grade_norm * 0.50
        + ela * 0.20
        + math * 0.10
        + growth * 0.10
        + grad * 0.05
        + career * 0.05
    )
    return round(score, 1)


# ---------------------------------------------------------------------------
# Step 1: Extract Orange County from FLDOE Excel
# ---------------------------------------------------------------------------
def download_fldoe():
    """Download FLDOE Excel if not cached locally."""
    if os.path.exists(FLDOE_LOCAL):
        print(f"  Using cached {FLDOE_LOCAL}")
        return FLDOE_LOCAL
    print(f"  Downloading FLDOE grades from {FLDOE_URL}...")
    req = urllib.request.Request(FLDOE_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        with open(FLDOE_LOCAL, "wb") as f:
            f.write(resp.read())
    print(f"  Saved to {FLDOE_LOCAL}")
    return FLDOE_LOCAL


def extract_orange_from_fldoe(xlsx_path):
    """Extract district 48 (Orange County) rows from FLDOE Excel."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active

    # Column mapping (0-indexed from row 4 headers)
    rows = []
    for row in ws.iter_rows(min_row=5, values_only=True):
        dist_num = str(row[0]).strip() if row[0] else ""
        if dist_num != "48":
            continue

        school_num = str(row[2]).strip().zfill(4) if row[2] else ""
        state_id = f"48{school_num}"
        school_name = str(row[4]).strip() if row[4] else ""
        charter = str(row[49]).strip() if row[49] else "NO"
        title_i = str(row[50]).strip() if row[50] else ""
        alt_ese = str(row[51]).strip() if row[51] else "N"
        school_type_code = str(row[52]).strip() if row[52] else ""
        grade_2025 = str(row[21]).strip() if row[21] else ""
        grade_2024 = str(row[22]).strip() if row[22] else ""
        econ_disadv = row[53] if row[53] else ""

        rows.append({
            "state_school_id": state_id,
            "district_number": "48",
            "district_name": "ORANGE",
            "school_number": school_num,
            "school_name": school_name,
            "school_type_code": school_type_code,
            "school_type_desc": TYPE_MAP.get(school_type_code, "Unknown"),
            "charter_school": charter,
            "title_i": title_i,
            "alternative_ese_center": alt_ese,
            "ela_achievement": row[6] if row[6] is not None else "",
            "ela_learning_gains": row[7] if row[7] is not None else "",
            "math_achievement": row[9] if row[9] is not None else "",
            "math_learning_gains": row[10] if row[10] is not None else "",
            "science_achievement": row[12] if row[12] is not None else "",
            "social_studies_achievement": row[13] if row[13] is not None else "",
            "graduation_rate": row[15] if row[15] is not None else "",
            "career_college_acceleration": row[16] if row[16] is not None else "",
            "total_points": row[17] if row[17] is not None else "",
            "total_components": row[18] if row[18] is not None else "",
            "percent_total_points": row[19] if row[19] is not None else "",
            "percent_tested": row[20] if row[20] is not None else "",
            "grade_2025": grade_2025,
            "grade_2024": grade_2024,
            "econ_disadv_pct": econ_disadv,
            "source_url": FLDOE_URL,
        })

    wb.close()
    return rows


# ---------------------------------------------------------------------------
# Step 2: Update CSV files
# ---------------------------------------------------------------------------
def append_fdoe_raw(orange_rows):
    """Append Orange County rows to FDOE_Grades_2025_Raw.csv."""
    path = os.path.join(CSV_DIR, "FDOE_Grades_2025_Raw.csv")
    with open(path) as f:
        existing = {r["state_school_id"] for r in csv.DictReader(f)}

    fieldnames = [
        "state_school_id", "district_number", "district_name", "school_number",
        "school_name", "school_type_code", "school_type_desc", "charter_school",
        "title_i", "alternative_ese_center", "ela_achievement", "ela_learning_gains",
        "math_achievement", "math_learning_gains", "science_achievement",
        "social_studies_achievement", "graduation_rate", "career_college_acceleration",
        "total_points", "total_components", "percent_total_points", "percent_tested",
        "grade_2025", "grade_2024", "econ_disadv_pct", "source_url",
    ]

    added = 0
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        for row in orange_rows:
            if row["state_school_id"] not in existing:
                w.writerow(row)
                added += 1

    print(f"  FDOE_Grades_2025_Raw.csv: added {added} new Orange County rows")
    return added


def append_school_master(orange_rows):
    """Append Orange County schools to school_master.csv."""
    path = os.path.join(CSV_DIR, "school_master.csv")
    with open(path) as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        existing = {r["state_school_id"] for r in reader}

    added = 0
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        for row in orange_rows:
            sid = row["state_school_id"]
            if sid in existing:
                continue

            is_charter = "YES" if row["charter_school"] == "YES" else "NO"
            alt_ese = row.get("alternative_ese_center", "N")
            is_private = "NO"

            # Determine school type for zoned public
            is_zoned = "YES" if is_charter == "NO" and alt_ese == "N" else "NO"

            w.writerow({
                "district": "ORANGE",
                "county": "ORANGE",
                "state_school_id": sid,
                "nces_id": "",
                "school_name": row["school_name"],
                "school_type": row["school_type_desc"],
                "is_zoned_public": is_zoned,
                "is_charter": is_charter,
                "is_magnet": "",
                "is_private": is_private,
                "grades_served": "",
                "address": "",
                "city": "",
                "zip": "",
                "latitude": "",
                "longitude": "",
                "source_url": FLDOE_URL,
                "notes": f"School type code {row['school_type_code']}; "
                         f"Title I={row['title_i']}; "
                         f"Alternative/ESE={alt_ese}; "
                         f"coordinates pending NCES/district GIS pull.",
            })
            added += 1

    print(f"  school_master.csv: added {added} new Orange County schools")
    return added


def append_school_performance(orange_rows):
    """Append Orange County schools to school_performance.csv."""
    path = os.path.join(CSV_DIR, "school_performance.csv")
    with open(path) as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        existing = {r["state_school_id"] for r in reader}

    added = 0
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        for row in orange_rows:
            sid = row["state_school_id"]
            if sid in existing:
                continue

            grade = row["grade_2025"]
            ela = safe_float(row["ela_achievement"])
            math = safe_float(row["math_achievement"])
            ela_gains = safe_float(row["ela_learning_gains"])
            math_gains = safe_float(row["math_learning_gains"])
            grad = safe_float(row["graduation_rate"])
            career = safe_float(row["career_college_acceleration"])

            # Growth = average of ELA + Math learning gains
            gains_count = 0
            gains_sum = 0.0
            if ela_gains > 0:
                gains_sum += ela_gains
                gains_count += 1
            if math_gains > 0:
                gains_sum += math_gains
                gains_count += 1
            growth = round(gains_sum / gains_count, 1) if gains_count > 0 else 0.0

            score = calc_score(grade, ela, math, ela_gains, math_gains, grad, career)

            w.writerow({
                "state_school_id": sid,
                "school_name": row["school_name"],
                "school_year": "2025",
                "fl_school_grade": grade,
                "grade_points": GRADE_MAP.get(grade, 0),
                "ela_achievement_pct": ela,
                "math_achievement_pct": math,
                "growth_pct": growth,
                "graduation_pct": grad,
                "career_college_readiness_pct": career,
                "public_zone_score": score,
                "source_url": FLDOE_URL,
                "notes": "Scored with workbook model: grade 50%, ELA 20%, "
                         "math 10%, growth(avg ELA+math gains) 10%, grad 5%, career 5%.",
            })
            added += 1

    print(f"  school_performance.csv: added {added} new Orange County schools")
    return added


# ---------------------------------------------------------------------------
# Step 3: Download zone boundaries from OCPS ArcGIS
# ---------------------------------------------------------------------------
def download_zones():
    """Download all zone polygons from OCPS ArcGIS FeatureServer."""
    all_features = {}

    for zone_type in ["ES", "MS", "HS", "K8", "PS8"]:
        offset = 0
        features = []
        while True:
            url = (
                f"{ZONE_URL}?where=TYPE%3D%27{zone_type}%27"
                f"&outFields=*&f=geojson"
                f"&resultOffset={offset}&resultRecordCount=500"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())

            batch = data.get("features", [])
            if not batch:
                break
            features.extend(batch)
            offset += len(batch)
            if len(batch) < 500:
                break

        all_features[zone_type] = features
        print(f"  Downloaded {len(features)} {zone_type} zones")

    return all_features


# ---------------------------------------------------------------------------
# Step 4: Match zones to school performance data
# ---------------------------------------------------------------------------
def build_school_lookup(orange_rows):
    """Build lookup from school name to performance data."""
    lookup = {}
    for row in orange_rows:
        name = row["school_name"].upper().strip()
        lookup[name] = {
            "name": row["school_name"],
            "grade": row["grade_2025"],
            "score": calc_score(
                row["grade_2025"],
                safe_float(row["ela_achievement"]),
                safe_float(row["math_achievement"]),
                safe_float(row["ela_learning_gains"]),
                safe_float(row["math_learning_gains"]),
                safe_float(row["graduation_rate"]),
                safe_float(row["career_college_acceleration"]),
            ),
            "ela_pct": safe_float(row["ela_achievement"]),
            "math_pct": safe_float(row["math_achievement"]),
        }
    return lookup


def normalize(name):
    """Strip common suffixes for fuzzy matching."""
    n = name.upper().strip()
    for suffix in [
        " ELEMENTARY SCHOOL", " ELEMENTARY", " MIDDLE SCHOOL",
        " SENIOR HIGH SCHOOL", " SENIOR HIGH", " HIGH SCHOOL",
        " MIDDLE", " HIGH", " K-8", " SCHOOL", " K8",
    ]:
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
    n = re.sub(r"[.\-']", "", n)
    return n.strip()


def match_school(zone_name, zone_type, lookup):
    """Try to match zone name to a school in lookup."""
    zu = zone_name.upper().strip()

    # Manual map first
    if zu in MANUAL_MAP:
        mapped = MANUAL_MAP[zu].upper()
        if mapped in lookup:
            return lookup[mapped]

    # Exact match
    if zu in lookup:
        return lookup[zu]

    # Build candidate names based on zone type
    type_suffixes = {
        "ES": [" ELEMENTARY SCHOOL", " ELEMENTARY"],
        "MS": [" MIDDLE SCHOOL", " MIDDLE"],
        "HS": [" HIGH SCHOOL", " SENIOR HIGH SCHOOL", " SENIOR HIGH"],
        "K8": [" SCHOOL", " K-8", ""],
        "PS8": [" SCHOOL", ""],
    }
    for suffix in type_suffixes.get(zone_type, [""]):
        candidate = zu + suffix
        if candidate in lookup:
            return lookup[candidate]

    # Normalized matching
    zn = normalize(zu)
    for name, props in lookup.items():
        if normalize(name) == zn:
            return props

    # Contains match
    for name, props in lookup.items():
        nn = normalize(name)
        if zn and nn and len(zn) > 3 and (zn in nn or nn in zn):
            return props

    return None


def process_zones(zone_features, lookup):
    """Convert ArcGIS features to our format, grouped by target file."""
    results = {"elementary": [], "middle": [], "high": []}
    matched = 0
    unmatched = 0
    unmatched_names = []

    for zone_type, features in zone_features.items():
        target = ARCGIS_TYPE_FILE.get(zone_type, "elementary")
        grade_band = ARCGIS_TYPE_MAP.get(zone_type, "Elementary")

        # K8 zones: add to both elementary and middle
        targets = [target]
        grade_bands = [grade_band]
        if zone_type == "K8" or zone_type == "PS8":
            targets = ["elementary", "middle"]
            grade_bands = ["Elementary", "Middle"]

        for feat in features:
            props = feat.get("properties", {})
            zone_name = props.get("SCHOOL", "").strip()
            if not zone_name:
                continue

            school = match_school(zone_name, zone_type, lookup)
            if school:
                matched += 1
                for t, gb in zip(targets, grade_bands):
                    new_props = {
                        "zone_name": zone_name,
                        "district": "ORANGE",
                        "grade_band": gb,
                        "grade": school.get("grade", "N/A"),
                        "score": school.get("score", 0),
                        "school_name": school["name"],
                        "ela_pct": school.get("ela_pct", 0),
                        "math_pct": school.get("math_pct", 0),
                    }
                    results[t].append({
                        "type": "Feature",
                        "geometry": feat["geometry"],
                        "properties": new_props,
                    })
            else:
                unmatched += 1
                unmatched_names.append(f"{zone_name} ({zone_type})")
                for t, gb in zip(targets, grade_bands):
                    new_props = {
                        "zone_name": zone_name,
                        "district": "ORANGE",
                        "grade_band": gb,
                        "grade": "N/A",
                        "score": 0,
                        "school_name": zone_name.upper(),
                        "ela_pct": 0,
                        "math_pct": 0,
                    }
                    results[t].append({
                        "type": "Feature",
                        "geometry": feat["geometry"],
                        "properties": new_props,
                    })

    print(f"  {matched} matched, {unmatched} unmatched")
    if unmatched_names:
        print("  Unmatched zones:")
        for n in sorted(unmatched_names):
            print(f"    {n}")

    return results


# ---------------------------------------------------------------------------
# Step 5: Merge into zone GeoJSON files
# ---------------------------------------------------------------------------
def update_zone_files(new_features):
    """Add Orange County features to zone GeoJSON files."""
    for level in ("elementary", "middle", "high"):
        path = ZONE_FILES[level]
        with open(path) as f:
            data = json.load(f)

        # Remove any existing Orange features
        old_count = len([
            f for f in data["features"]
            if f["properties"].get("district") == "ORANGE"
        ])
        data["features"] = [
            f for f in data["features"]
            if f["properties"].get("district") != "ORANGE"
        ]
        data["features"].extend(new_features[level])

        with open(path, "w") as f:
            json.dump(data, f)

        if old_count:
            print(f"  {level}: replaced {old_count} old -> {len(new_features[level])} new Orange zones")
        else:
            print(f"  {level}: added {len(new_features[level])} Orange zones")


# ---------------------------------------------------------------------------
# Step 6: Rebuild index.html inline data
# ---------------------------------------------------------------------------
def rebuild_index_html(orange_rows):
    """Rebuild SCHOOLS and BOUNDARIES in index.html."""
    html_path = os.path.join(BASE, "index.html")
    with open(html_path) as f:
        lines = f.readlines()

    # --- Update SCHOOLS (line 98, 0-indexed 97) ---
    schools_line = lines[97]
    schools_json = schools_line.strip().rstrip(";")[len("const SCHOOLS = "):]
    schools = json.loads(schools_json)

    # Build Orange County school features (without coordinates they won't show as points,
    # but they'll be in the data for zone matching)
    perf_lookup = {}
    for row in orange_rows:
        sid = row["state_school_id"]
        grade = row["grade_2025"]
        ela = safe_float(row["ela_achievement"])
        math = safe_float(row["math_achievement"])
        ela_gains = safe_float(row["ela_learning_gains"])
        math_gains = safe_float(row["math_learning_gains"])
        grad = safe_float(row["graduation_rate"])
        career = safe_float(row["career_college_acceleration"])

        gains_count = 0
        gains_sum = 0.0
        if ela_gains > 0:
            gains_sum += ela_gains
            gains_count += 1
        if math_gains > 0:
            gains_sum += math_gains
            gains_count += 1
        growth = round(gains_sum / gains_count, 1) if gains_count > 0 else 0.0

        score = calc_score(grade, ela, math, ela_gains, math_gains, grad, career)

        perf_lookup[row["school_name"].upper().strip()] = {
            "id": sid,
            "name": row["school_name"],
            "district": "ORANGE",
            "county": "ORANGE",
            "type": row["school_type_desc"],
            "grades_served": "",
            "grade": grade,
            "score": score,
            "ela_pct": ela,
            "math_pct": math,
            "growth_pct": growth,
            "grad_pct": grad,
            "is_charter": row["charter_school"],
            "is_magnet": "",
            "is_private": "NO",
        }

    # We don't have geocodes yet, so Orange schools won't appear as map points.
    # They ARE in the data so zone boundaries can look them up for scoring.
    # Just ensure the data is consistent.

    # Write updated SCHOOLS
    lines[97] = "const SCHOOLS = " + json.dumps(schools, separators=(",", ":")) + ";\n"

    # --- Update BOUNDARIES (line 99, 0-indexed 98) ---
    boundaries = {}
    for level in ("elementary", "middle", "high"):
        with open(ZONE_FILES[level]) as f:
            boundaries[level] = json.load(f)

    lines[98] = "const BOUNDARIES = " + json.dumps(boundaries, separators=(",", ":")) + ";\n"

    with open(html_path, "w") as f:
        f.writelines(lines)

    # Count Orange zones in boundaries
    total_zones = 0
    for level, fc in boundaries.items():
        count = len([
            f for f in fc["features"]
            if f["properties"].get("district") == "ORANGE"
        ])
        total_zones += count
        print(f"  {level}: {count} Orange zones in BOUNDARIES")

    print(f"  Updated index.html (BOUNDARIES with {total_zones} Orange zones)")


# ---------------------------------------------------------------------------
# Step 7: Update zone_master.csv
# ---------------------------------------------------------------------------
def update_zone_master():
    """Add Orange County entries to zone_master.csv."""
    path = os.path.join(CSV_DIR, "zone_master.csv")
    with open(path) as f:
        content = f.read()

    if "ORANGE" in content:
        print("  zone_master.csv: Orange County already present")
        return

    arcgis_url = (
        "https://services1.arcgis.com/OIHmIXKmWvkweUZp/arcgis/rest/services/"
        "Find_My_School_2526_Online/FeatureServer/1"
    )
    new_rows = [
        f"ORANGE_ZONE_SRC,ORANGE,ORANGE,All,2025-26,,,{arcgis_url},SCHOOL/TYPE,"
        f"Source registered,{arcgis_url},"
        f"OCPS ArcGIS FeatureServer layer 1; TYPE field: ES/MS/HS/K8/PS8.\n"
    ]

    with open(path, "a") as f:
        for row in new_rows:
            f.write(row)

    print("  zone_master.csv: added Orange County source entry")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Adding Orange County Public Schools")
    print("=" * 60)

    # Step 1: Extract FLDOE data
    print("\n[1/7] Extracting Orange County from FLDOE grades...")
    xlsx_path = download_fldoe()
    orange_rows = extract_orange_from_fldoe(xlsx_path)
    print(f"  Found {len(orange_rows)} schools")

    # Step 2: Update CSVs
    print("\n[2/7] Updating CSV data files...")
    append_fdoe_raw(orange_rows)
    append_school_master(orange_rows)
    append_school_performance(orange_rows)

    # Step 3: Download zone boundaries
    print("\n[3/7] Downloading OCPS attendance zone boundaries...")
    zone_features = download_zones()

    # Step 4: Match zones to schools
    print("\n[4/7] Matching zones to school performance data...")
    lookup = build_school_lookup(orange_rows)
    processed = process_zones(zone_features, lookup)

    # Step 5: Update zone files
    print("\n[5/7] Updating zone GeoJSON files...")
    update_zone_files(processed)

    # Step 6: Rebuild index.html
    print("\n[6/7] Rebuilding index.html inline data...")
    rebuild_index_html(orange_rows)

    # Step 7: Update zone master
    print("\n[7/7] Updating zone_master.csv...")
    update_zone_master()

    print("\n" + "=" * 60)
    print("Done! Orange County added successfully.")
    print("=" * 60)

    # Summary
    for level in ("elementary", "middle", "high"):
        with open(ZONE_FILES[level]) as f:
            data = json.load(f)
        by_dist = {}
        for feat in data["features"]:
            d = feat["properties"].get("district", "?")
            by_dist[d] = by_dist.get(d, 0) + 1
        print(f"\n{level} zones: {json.dumps(by_dist)}")


if __name__ == "__main__":
    main()
