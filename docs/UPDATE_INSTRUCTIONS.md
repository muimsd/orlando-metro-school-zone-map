# Orlando Metro School Zone Map — Update & Refresh Guide

## Project Structure

```
jaredjones141-school/
├── index.html                          # Interactive Mapbox GL JS map (open in browser)
├── workbook.xlsx                       # Original populated workbook
├── data/
│   ├── csv_exports/                    # Exported workbook sheets
│   │   ├── school_master.csv           # 324 schools with classifications
│   │   ├── school_performance.csv      # FDOE grades + zone scores
│   │   ├── FDOE_Grades_2025_Raw.csv    # Raw 2025 school grades
│   │   ├── zone_master.csv             # Boundary source registry
│   │   ├── program_master.csv          # Magnet/charter/private program info
│   │   ├── Scoring_Model.csv           # Scoring weights
│   │   ├── Map_Config.csv              # Map layer configuration
│   │   └── Source_Register.csv         # Official data source URLs
│   ├── schools/
│   │   ├── nces_geocodes.csv           # All 324 schools geocoded (lat/lng)
│   │   ├── elementary_schools.geojson  # Elementary school points
│   │   ├── middle_schools.geojson      # Middle school points
│   │   ├── high_schools.geojson        # High school points
│   │   ├── charter_schools.geojson     # Charter school points
│   │   ├── magnet_schools.geojson      # Magnet school points (placeholder)
│   │   ├── private_schools.geojson     # Private school points (placeholder)
│   │   └── all_schools.geojson         # Combined GeoJSON
│   └── boundaries/                     # District attendance zone polygons (pending)
├── scripts/                            # Build/ETL scripts
└── docs/
    └── UPDATE_INSTRUCTIONS.md          # This file
```

## How to Refresh School Grade Data

1. Download new school grades from: https://www.fldoe.org/accountability/accountability-reporting/school-grades/
2. Filter to Lake, Osceola, Polk, Seminole counties
3. Update `data/csv_exports/school_performance.csv` with new grades and recalculated zone scores
4. Re-run the GeoJSON builder script to regenerate the school GeoJSON files
5. The HTML map loads GeoJSON inline — rebuild index.html with updated data

## How to Add Attendance Zone Boundaries

When you obtain district boundary shapefiles:

1. Convert shapefiles to GeoJSON (use ogr2ogr or mapshaper.org):
   ```bash
   ogr2ogr -f GeoJSON -t_srs EPSG:4326 output.geojson input.shp
   ```
2. Place in `data/boundaries/` named as `{district}_{gradeband}.geojson`
3. Add as a new source/layer in index.html to render choropleth polygons

## Boundary Data Sources (Official)

| District | Source | Status |
|----------|--------|--------|
| Osceola | https://www.osceolaschools.net/42204_4 | Shapefiles available for download (K-5, 6-8, 9-12) |
| Seminole | Contact GIS: jnoran@seminolecountyfl.gov / (407) 665-1147 | Zone maps available, shapefiles need request |
| Polk | https://azua.polk-fl.net/ | Interactive tool only, contact Pupil Accounting (863) 519-7600 |
| Lake | https://www.lake.k12.fl.us/page/school-locator | ArcGIS service was offline; contact district |

## How to Add Private / Magnet Schools

1. Update `school_master.csv` — set `is_private=YES` or `is_magnet=YES`
2. Add coordinates to `nces_geocodes.csv`
3. Re-run GeoJSON builder
4. Private schools should NOT use public_zone_score (per Scoring_Model)

## Mapbox Token

Set your Mapbox token in `config.js` (not committed to git):
```js
// config.js
const MAPBOX_TOKEN = 'pk.your_token_here';
```
The token is loaded by index.html via a script tag. Create this file locally after cloning.

## Geocoding

Schools were geocoded using Nominatim (OpenStreetMap) + Mapbox Geocoding API as fallback.
To re-geocode, use the Mapbox Geocoding API:
```
https://api.mapbox.com/geocoding/v5/mapbox.places/{query}.json?access_token={TOKEN}&country=US
```

## Future Enhancements

- Add polygon choropleth layers when boundary shapefiles are obtained
- Add Voronoi approximation of attendance zones from school points
- Integrate GreatSchools or Niche ratings (requires licensing)
- Add Orange County data for full Orlando metro coverage
