"""Write public/map-periods.json, the historical layers of the map page: territories and dioceses for a period.

    python scripts/make-map-periods.py "Mint authorities.geojson" diocese1350.json diocese1450.json

Needs shapely (``pip install shapely``). The sources:

- the territories are Rombert Stapel's dated polygons of the authorities of the Low Countries, "Mint Authorities of
  the Low Countries" (DataverseNL, https://doi.org/10.34894/PB9AT3, CC BY-NC-SA 4.0); a period shows the polygons
  in force in one year;
- the dioceses are the "Digital Atlas of Dioceses and Ecclesiastical Provinces in Late Medieval Europe (1200-1500)"
  by Rowan Dorin and others (Stanford Digital Repository, https://purl.stanford.edu/rh195hm5975, CC BY 3.0), ca.
  1350 and ca. 1450.

The places on the map keep their present-day coordinates: a layer only draws the boundaries under them. The
projection is the one of make-map-base.py and the map page (mapX, mapY in src/App.svelte).
"""

import json
import sys
from pathlib import Path

from shapely.geometry import box, shape
from shapely.ops import polylabel, unary_union

W, H = 800, 669
# The frame of the map, with a margin so that a boundary does not stop at the edge when the map is dragged.
VIEW = box(2.2, 49.25, 6.75, 51.8)
# Labels go on the part of a territory inside the map as it first shows, a little in from the edges.
LABEL_FRAME = box(2.6, 49.5, 6.35, 51.48)
# Simplification in degrees: about one pixel of the map at full view.
TOLERANCE = 0.004

# The cross-section of each period: a year inside it for the territories, a century for the dioceses.
PERIODS = {
    "medieval": {"year": 1350, "dioceses": 0},
    "burgundian": {"year": 1470, "dioceses": 1},
    "early-modern": {"year": 1700, "dioceses": None},
}

# Names in the site's three languages; a territory or diocese not listed is drawn without a label.
NAMES = {
    "Flanders": ("Flandre", "Vlaanderen", "Flanders"),
    "Brabant": ("Brabant", "Brabant", "Brabant"),
    "Hainaut": ("Hainaut", "Henegouwen", "Hainaut"),
    "Liège": ("Liège", "Luik", "Liège"),
    "Liege": ("Liège", "Luik", "Liège"),
    "Namur": ("Namur", "Namen", "Namur"),
    "Luxembourg": ("Luxembourg", "Luxemburg", "Luxembourg"),
    "Loon": ("Looz", "Loon", "Loon"),
    "Chiny": ("Chiny", "Chiny", "Chiny"),
    "Artois": ("Artois", "Artesië", "Artois"),
    "Jülich": ("Juliers", "Gulik", "Jülich"),
    "Guelders": ("Gueldre", "Gelre", "Guelders"),
    "Zeeland": ("Zélande", "Zeeland", "Zeeland"),
    "Holland": ("Hollande", "Holland", "Holland"),
    "Cleves": ("Clèves", "Kleef", "Cleves"),
    "Stavelot-Malmedy": ("Stavelot-Malmedy", "Stavelot-Malmedy", "Stavelot-Malmedy"),
    "Cambrai": ("Cambrai", "Kamerijk", "Cambrai"),
    "Tournai": ("Tournai", "Doornik", "Tournai"),
    "Limburg": ("Limbourg", "Limburg", "Limburg"),
    "Mechelen": ("Malines", "Mechelen", "Mechelen"),
    "Vermandois": ("Vermandois", "Vermandois", "Vermandois"),
    "Brabant of the States": ("Brabant des États", "Staats-Brabant", "States Brabant"),
    "Flanders of the States": ("Flandre des États", "Staats-Vlaanderen", "States Flanders"),
    "Overmaas of the States": ("Outre-Meuse des États", "Staats-Overmaas", "States Overmaas"),
    "Upper Guelders (Spain)": ("Haute-Gueldre", "Opper-Gelre", "Upper Guelders"),
    "Therouanne": ("Thérouanne", "Terwaan", "Thérouanne"),
    "Arras": ("Arras", "Atrecht", "Arras"),
    "Utrecht": ("Utrecht", "Utrecht", "Utrecht"),
    "Cologne (Koln)": ("Cologne", "Keulen", "Cologne"),
    "Trier": ("Trèves", "Trier", "Trier"),
    "Reims": ("Reims", "Reims", "Reims"),
    "Laon": ("Laon", "Laon", "Laon"),
    "Noyon": ("Noyon", "Noyon", "Noyon"),
    "Amiens": ("Amiens", "Amiens", "Amiens"),
    "Metz": ("Metz", "Metz", "Metz"),
    "Verdun": ("Verdun", "Verdun", "Verdun"),
}
# Below this area (square degrees, inside the frame) a territory gets no label: the small lordships of the Meuse.
LABEL_AREA = 0.04

CREDIT = {
    "territories": "Rombert Stapel, Mint Authorities of the Low Countries (DataverseNL, 2016–2025), "
    "https://doi.org/10.34894/PB9AT3, CC BY-NC-SA 4.0",
    "dioceses": "Rowan Dorin et al., Digital Atlas of Dioceses and Ecclesiastical Provinces in Late Medieval Europe "
    "(1200–1500), Stanford Digital Repository, https://purl.stanford.edu/rh195hm5975, CC BY 3.0",
}


def x(lon):
    return round((lon - 2.5) / 3.95 * W, 1)


def y(lat):
    return round((51.55 - lat) / 2.1 * H, 1)


def ring_path(coords):
    points = []
    for lon, lat in coords:
        point = (x(lon), y(lat))
        if not points or point != points[-1]:
            points.append(point)
    if len(points) < 4:
        return ""
    return "M" + "L".join(f"{a:g},{b:g}" for a, b in points) + "Z"


def path(geometry):
    polygons = getattr(geometry, "geoms", [geometry])
    return "".join(
        ring_path(ring.coords)
        for polygon in polygons
        if polygon.geom_type == "Polygon"
        for ring in [polygon.exterior, *polygon.interiors]
    )


def shapes(named):
    """One drawn shape per name: the parts clipped to the frame, merged, simplified, with a label point."""
    out = []
    for name, parts in named.items():
        geometry = unary_union(parts).intersection(VIEW)
        if geometry.is_empty or geometry.area < 0.002:
            continue
        drawn = geometry.simplify(TOLERANCE, preserve_topology=True)
        item = {"d": path(drawn)}
        shown = geometry.intersection(LABEL_FRAME)
        if name in NAMES and shown.area >= LABEL_AREA:
            largest = max(getattr(shown, "geoms", [shown]), key=lambda part: part.area)
            point = polylabel(largest, tolerance=0.01)
            item.update(dict(zip(("fr", "nl", "en"), NAMES[name])), x=x(point.x), y=y(point.y))
        out.append(item)
    return out


def territories(features, year):
    named = {}
    for feature in features:
        properties = feature["properties"]
        if int(properties["DATEfrom"][:4]) <= year <= int(properties["DATEto"][:4]):
            named.setdefault(properties["AUTHORITY"], []).append(shape(feature["geometry"]).buffer(0))
    return shapes(named)


def dioceses(features):
    named = {}
    for feature in features:
        named.setdefault(feature["properties"]["Dioc_Prov_"], []).append(shape(feature["geometry"]).buffer(0))
    return shapes(named)


def features(path_):
    return json.loads(Path(path_).read_text(encoding="utf-8"))["features"]


authorities, *centuries = sys.argv[1:]
authority_features = features(authorities)
diocese_features = [features(century) for century in centuries]
layers = {}
for period, cut in PERIODS.items():
    layer = {"year": cut["year"], "territories": territories(authority_features, cut["year"])}
    if cut["dioceses"] is not None:
        layer["diocesesYear"] = (1350, 1450)[cut["dioceses"]]
        layer["dioceses"] = dioceses(diocese_features[cut["dioceses"]])
    layers[period] = layer
out = Path(__file__).resolve().parent.parent / "public" / "map-periods.json"
out.write_text(json.dumps({"layers": layers, "credit": CREDIT}, ensure_ascii=False), encoding="utf-8")
print(f"{out}: {out.stat().st_size} bytes")
for period, layer in layers.items():
    labels = [item["en"] for item in layer["territories"] if "en" in item]
    print(period, len(layer["territories"]), "territories,", len(layer.get("dioceses", [])), "dioceses;", ", ".join(labels))
