#!/usr/bin/env python3
"""
Recalculate public_zone_score using exact workbook Scoring_Model weights,
using the average of ELA + Math learning gains for the growth component.

Weights (from Scoring_Model sheet):
  FL school grade:     50%  (A=4,B=3,C=2,D=1,F=0 -> normalized to 0-100)
  ELA achievement:     20%
  Math achievement:    10%
  Growth (avg gains):  10%
  Graduation rate:      5%
  College/career:       5%

Then rebuild SCHOOLS inline data in index.html and zone GeoJSON files.
"""
import csv
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

GRADE_MAP = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}


def safe_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def calc_score(grade_letter, ela, math, ela_gains, math_gains, grad, career):
    grade_pts = GRADE_MAP.get(grade_letter, 0)
    grade_norm = (grade_pts / 4.0) * 100.0

    # Average of ELA and math learning gains for growth
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


def main():
    # Load FDOE raw for both learning gains fields
    raw_path = os.path.join(DATA, "csv_exports/FDOE_Grades_2025_Raw.csv")
    with open(raw_path) as f:
        raw = {r["state_school_id"]: r for r in csv.DictReader(f)}

    # Update school_performance.csv
    perf_path = os.path.join(DATA, "csv_exports/school_performance.csv")
    with open(perf_path) as f:
        perf_rows = list(csv.DictReader(f))

    changed = 0
    for row in perf_rows:
        sid = row["state_school_id"]
        r = raw.get(sid, {})
        grade_letter = row["fl_school_grade"]
        ela = safe_float(row["ela_achievement_pct"])
        math = safe_float(row["math_achievement_pct"])
        ela_gains = safe_float(r.get("ela_learning_gains", 0))
        math_gains = safe_float(r.get("math_learning_gains", 0))
        grad = safe_float(r.get("graduation_rate", row.get("graduation_pct", 0)))
        career = safe_float(r.get("career_college_acceleration", row.get("career_college_readiness_pct", 0)))

        # Update growth_pct to average of both gains
        gains_count = 0
        gains_sum = 0.0
        if ela_gains > 0:
            gains_sum += ela_gains
            gains_count += 1
        if math_gains > 0:
            gains_sum += math_gains
            gains_count += 1
        new_growth = round(gains_sum / gains_count, 1) if gains_count > 0 else 0.0

        new_score = calc_score(grade_letter, ela, math, ela_gains, math_gains, grad, career)
        old_score = safe_float(row["public_zone_score"])

        if abs(new_score - old_score) > 0.05 or abs(new_growth - safe_float(row["growth_pct"])) > 0.05:
            changed += 1

        row["growth_pct"] = str(new_growth)
        row["public_zone_score"] = str(new_score)
        row["graduation_pct"] = str(safe_float(r.get("graduation_rate", row.get("graduation_pct", 0))))
        row["career_college_readiness_pct"] = str(safe_float(r.get("career_college_acceleration", row.get("career_college_readiness_pct", 0))))
        row["notes"] = "Scored with workbook model: grade 50%, ELA 20%, math 10%, growth(avg ELA+math gains) 10%, grad 5%, career 5%."

    # Write updated CSV
    fieldnames = list(perf_rows[0].keys())
    with open(perf_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(perf_rows)
    print(f"Updated school_performance.csv: {changed} scores changed out of {len(perf_rows)}")

    # Build score lookup for updating SCHOOLS and BOUNDARIES in index.html
    score_lookup = {}
    for row in perf_rows:
        score_lookup[row["state_school_id"]] = {
            "score": safe_float(row["public_zone_score"]),
            "growth_pct": safe_float(row["growth_pct"]),
            "grad_pct": safe_float(row["graduation_pct"]),
        }

    # Update SCHOOLS in index.html (line 98)
    html_path = os.path.join(BASE, "index.html")
    with open(html_path) as f:
        lines = f.readlines()

    schools_line = lines[97]  # line 98 (0-indexed)
    schools_json = schools_line.strip().rstrip(";")[len("const SCHOOLS = "):]
    schools = json.loads(schools_json)

    schools_updated = 0
    for cat, fc in schools.items():
        for feat in fc["features"]:
            p = feat["properties"]
            sid = p.get("id", "")
            if sid in score_lookup:
                sl = score_lookup[sid]
                if abs(p.get("score", 0) - sl["score"]) > 0.05:
                    schools_updated += 1
                p["score"] = sl["score"]
                p["growth_pct"] = sl["growth_pct"]
                p["grad_pct"] = sl["grad_pct"]

    lines[97] = "const SCHOOLS = " + json.dumps(schools, separators=(",", ":")) + ";\n"
    print(f"Updated SCHOOLS in index.html: {schools_updated} schools with changed scores")

    # Update BOUNDARIES in index.html (line 99) - update scores in zone properties
    bounds_line = lines[98]  # line 99
    bounds_json = bounds_line.strip().rstrip(";")[len("const BOUNDARIES = "):]
    boundaries = json.loads(bounds_json)

    # Build name-to-score lookup from schools
    name_score = {}
    for cat, fc in schools.items():
        for feat in fc["features"]:
            p = feat["properties"]
            name_score[p["name"].upper().strip()] = {
                "score": p.get("score", 0),
                "ela_pct": p.get("ela_pct", 0),
                "math_pct": p.get("math_pct", 0),
            }

    zones_updated = 0
    for level, fc in boundaries.items():
        for feat in fc["features"]:
            p = feat["properties"]
            sname = p.get("school_name", "").upper().strip()
            if sname in name_score:
                ns = name_score[sname]
                if abs(p.get("score", 0) - ns["score"]) > 0.05:
                    zones_updated += 1
                p["score"] = ns["score"]

    lines[98] = "const BOUNDARIES = " + json.dumps(boundaries, separators=(",", ":")) + ";\n"
    print(f"Updated BOUNDARIES in index.html: {zones_updated} zones with changed scores")

    # Also update the zone GeoJSON files on disk
    bounds_dir = os.path.join(DATA, "boundaries")
    for level in ("elementary", "middle", "high"):
        path = os.path.join(bounds_dir, f"{level}_zones.geojson")
        with open(path) as f:
            data = json.load(f)
        for feat in data["features"]:
            p = feat["properties"]
            sname = p.get("school_name", "").upper().strip()
            if sname in name_score:
                p["score"] = name_score[sname]["score"]
        with open(path, "w") as f:
            json.dump(data, f)

    with open(html_path, "w") as f:
        f.writelines(lines)

    print("\nDone! Scoring model fully applied.")

    # Show some examples of changed scores
    print("\nSample score changes (old -> new using avg(ELA+math) gains):")
    for row in perf_rows[:10]:
        sid = row["state_school_id"]
        r = raw.get(sid, {})
        ela_g = safe_float(r.get("ela_learning_gains", 0))
        math_g = safe_float(r.get("math_learning_gains", 0))
        if math_g > 0 and abs(ela_g - math_g) > 1:
            print(f"  {row['school_name'][:45]:45s} ELA_gains={ela_g:.0f} Math_gains={math_g:.0f} growth={row['growth_pct']} score={row['public_zone_score']}")


if __name__ == "__main__":
    main()
