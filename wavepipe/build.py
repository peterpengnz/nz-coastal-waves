"""Turns a cropped wave grid into small static JSON files a client can fetch.

Output (schema 1) under OUT/v1/:
  meta.json            run, provider, model, grid, attribution, times (epoch s), radiusKm
  cells.json           {"lat":[...], "lon":[...]}  every published sea cell (4 dp)
  tiles/<lat>_<lon>.json  cells whose floor(lat), floor(lon) match, with series:
      {"lat","lon","hs":[cm],"dir":[deg],"per":[ds], optional "hsSw","perSw","hsWw"}
  Integers keep files small; null = no data for that step (never 0).

Published cells = for every location in locations.json (tide stations,
secondary ports, coastal places) its nearest valid sea cell, plus every sea
cell within RADIUS_KM of any location (so an arbitrary coastal point also
finds a cell). Clients should pick the nearest published cell and treat
> MAX_MATCH_KM as "no wave data here".
"""
from __future__ import annotations

import json
import math
import os
import shutil

import numpy as np
import xarray as xr

SCHEMA = 1
PROJECT = os.environ.get("WAVES_PROJECT_NAME", "nz-coastal-waves")
RADIUS_KM = 40.0
MAX_MATCH_KM = 60.0  # advertised in meta.json; enforced by clients
R = 6371.0


def data_terms(attrs: dict) -> dict:
    """Licence of the published files depends on the upstream source (see LICENSE-DATA.md).

    ECMWF open data is CC BY 4.0, so our output can be CC BY 4.0 too. Copernicus
    Marine products come under the Copernicus Marine Service licence, whose clause
    2.6 (traceability records) must be passed on to downstream users; CC BY 4.0
    forbids extra conditions, so Copernicus-derived output keeps that licence.
    """
    if attrs.get("licence") == "CC-BY-4.0":
        return {"dataLicence": "CC-BY-4.0",
                "credit": f"Wave forecast processed by {PROJECT} (CC BY 4.0). {attrs['attribution']}"}
    return {"dataLicence": "Copernicus-Marine-Service-Licence",
            "licenceUrl": "https://marine.copernicus.eu/user-corner/service-commitments-and-licence",
            "credit": f"{attrs['attribution']} Processed by {PROJECT}."}


def load_points(path: str) -> np.ndarray:
    """locations.json ({"locations": [[name, lat, lon, kind], ...]}) or the app's refdata.json."""
    with open(path, encoding="utf-8") as f:
        ref = json.load(f)
    if "locations" in ref:
        pts = [(row[1], row[2]) for row in ref["locations"]]
    else:
        pts = [(s["lat"], s["lon"]) for k in ("stations", "secondaryPorts", "secondarySpots", "placeNames") for s in ref[k]]
    arr = np.unique(np.array(pts, dtype="float64"), axis=0)
    # Only points inside the forecast box (drops e.g. Scott Base, Antarctica).
    from .sources import LAT_MAX, LAT_MIN, LON_E, LON_W
    inside = (arr[:, 0] >= LAT_MIN) & (arr[:, 0] <= LAT_MAX) & ((arr[:, 1] >= LON_W) | (arr[:, 1] <= LON_E))
    return arr[inside]


def _haversine(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlat = p2 - p1
    dlon = np.radians(((lon2 - lon1 + 180) % 360) - 180)
    a = np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(np.minimum(a, 1.0)))


def select_cells(ds: xr.Dataset, points: np.ndarray, radius_km: float = RADIUS_KM):
    valid = np.isfinite(ds["hs"].values).any(axis=0)
    lat2d, lon2d = np.meshgrid(ds["lat"].values, ds["lon"].values, indexing="ij")
    clat, clon = lat2d[valid], lon2d[valid]
    idx = np.argwhere(valid)
    keep = np.zeros(clat.size, dtype=bool)
    nearest_km = np.empty(len(points))
    for start in range(0, len(points), 200):
        p = points[start:start + 200]
        d = _haversine(p[:, :1], p[:, 1:2], clat[None, :], clon[None, :])
        keep |= (d <= radius_km).any(axis=0)
        nn = d.argmin(axis=1)
        keep[nn] = True
        nearest_km[start:start + 200] = d[np.arange(len(p)), nn]
    return idx[keep], clat[keep], clon[keep], nearest_km


def _series(arr: np.ndarray, scale: float) -> list:
    return [None if not math.isfinite(float(v)) else int(round(float(v) * scale)) for v in arr]


def build(ds: xr.Dataset, refdata_path: str, out_dir: str) -> dict:
    points = load_points(refdata_path)
    idx, clat, clon, nearest_km = select_cells(ds, points)
    times = [int(np.datetime64(t, "s").astype("int64")) for t in ds["time"].values]
    root = os.path.join(out_dir, "v1")
    if os.path.isdir(root):
        shutil.rmtree(root)
    os.makedirs(os.path.join(root, "tiles"))

    extra = [("hs_sw", "hsSw", 100), ("per_sw", "perSw", 10), ("hs_ww", "hsWw", 100)]
    tiles: dict[str, list] = {}
    for (i, j), la, lo in zip(idx, clat, clon):
        cell = {
            "lat": round(float(la), 4), "lon": round(float(lo), 4),
            "hs": _series(ds["hs"].values[:, i, j], 100),
            "dir": _series(ds["dir"].values[:, i, j], 1),
            "per": _series(ds["per"].values[:, i, j], 10),
        }
        for var, key, scale in extra:
            if var in ds:
                cell[key] = _series(ds[var].values[:, i, j], scale)
        key = f"{math.floor(la)}_{math.floor(lo)}"
        tiles.setdefault(key, []).append(cell)

    for key, cells in tiles.items():
        with open(os.path.join(root, "tiles", f"{key}.json"), "w") as f:
            json.dump({"schema": SCHEMA, "run": ds.attrs["run"], "times": times, "cells": cells}, f, separators=(",", ":"))
    with open(os.path.join(root, "cells.json"), "w") as f:
        json.dump({"schema": SCHEMA, "run": ds.attrs["run"],
                   "lat": [round(float(v), 4) for v in clat], "lon": [round(float(v), 4) for v in clon]}, f, separators=(",", ":"))
    meta = {
        "schema": SCHEMA, "run": ds.attrs["run"], "provider": ds.attrs["provider"], "model": ds.attrs["model"],
        "gridDeg": ds.attrs["grid_deg"], "attribution": ds.attrs["attribution"], "upstreamLicence": ds.attrs["licence"],
        **data_terms(ds.attrs),
        "times": times, "radiusKm": RADIUS_KM, "maxMatchKm": MAX_MATCH_KM,
        "fields": {"hs": "cm", "dir": "deg from", "per": "0.1 s", "hsSw": "cm", "perSw": "0.1 s", "hsWw": "cm"},
        "cells": int(clat.size), "tiles": len(tiles),
    }
    with open(os.path.join(root, "meta.json"), "w") as f:
        json.dump(meta, f, separators=(",", ":"), ensure_ascii=False)
    return {
        "cells": int(clat.size), "tiles": len(tiles), "steps": len(times), "points": int(len(points)),
        "point_to_cell_km_p50": float(np.percentile(nearest_km, 50)),
        "point_to_cell_km_p95": float(np.percentile(nearest_km, 95)),
        "point_to_cell_km_max": float(nearest_km.max()),
        "bytes": sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(root) for f in fs),
    }
