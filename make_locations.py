#!/usr/bin/env python3
"""Builds locations.json (the points that decide which sea cells are published)
from a reference file with stations / secondaryPorts / secondarySpots /
placeNames arrays. Output keeps only name, lat, lon and kind.

  python make_locations.py refdata.json > locations.json
"""
import json
import sys

ref = json.load(open(sys.argv[1], encoding="utf-8"))
rows, seen = [], set()
for key, kind in (("stations", "tide-station"), ("secondaryPorts", "secondary-port"),
                  ("secondarySpots", "coastal-spot"), ("placeNames", "place")):
    for s in ref[key]:
        k = (s["name"], round(s["lat"], 4), round(s["lon"], 4))
        if k in seen:
            continue
        seen.add(k)
        rows.append([s["name"], round(s["lat"], 4), round(s["lon"], 4), kind])
json.dump({
    "description": "New Zealand tide stations, secondary ports and coastal places used to choose published wave cells.",
    "sources": "Tide stations and secondary ports: Land Information New Zealand (LINZ), CC BY 4.0. "
               "Place names: GeoNames (CC BY 4.0) and LINZ.",
    "columns": ["name", "lat", "lon", "kind"],
    "locations": rows,
}, sys.stdout, ensure_ascii=False, separators=(",", ":"))
