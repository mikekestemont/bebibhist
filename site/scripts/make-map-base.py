"""Write public/map-base.json, the minimalist base map under the places, from geoBoundaries outlines.

    python3 scripts/make-map-base.py ADM0.geojson ADM1.geojson ADM3.geojson

The files are the simplified GeoJSON of geoBoundaries for Belgium (gbOpen, BEL): ADM0 the country and ADM1 the
regions (Eurostat, CC BY 4.0), ADM3 the arrondissements (CC0). The projection is the one the map page uses
(mapX, mapY in src/App.svelte); points closer than a fraction of a pixel are dropped.
"""

import json
import sys
from pathlib import Path

W, H = 800, 669


def x(lon):
    return (lon - 2.5) / 3.95 * W


def y(lat):
    return (51.55 - lat) / 2.1 * H


def ring_path(ring, tolerance):
    points = []
    for lon, lat in ring:
        point = (round(x(lon), 1), round(y(lat), 1))
        if points and abs(point[0] - points[-1][0]) < tolerance and abs(point[1] - points[-1][1]) < tolerance:
            continue
        points.append(point)
    if len(points) < 3:
        return ""
    return "M" + "L".join(f"{a:g},{b:g}" for a, b in points) + "Z"


def geometry_path(geometry, tolerance):
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return "".join(ring_path(ring, tolerance) for polygon in polygons for ring in polygon)


def features(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))["features"]


country, regions, arrondissements = sys.argv[1:4]
base = {
    "country": geometry_path(features(country)[0]["geometry"], 0.4),
    "regions": [geometry_path(feature["geometry"], 0.4) for feature in features(regions)],
    "arrondissements": [geometry_path(feature["geometry"], 0.6) for feature in features(arrondissements)],
    "credit": "Boundaries: geoBoundaries (Eurostat, CC BY 4.0; arrondissements CC0)",
}
out = Path(__file__).resolve().parent.parent / "public" / "map-base.json"
out.write_text(json.dumps(base), encoding="utf-8")
print(f"{out}: {out.stat().st_size} bytes")
