import json
import math
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from wavepipe import build, sources  # noqa: E402


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ref = os.path.join(self.tmp, "ref.json")
        # Two coastal points west of the synthetic "land" and one far inland/east.
        json.dump({"stations": [{"name": "A", "lat": -37.8, "lon": 174.8}], "secondaryPorts": [],
                   "secondarySpots": [{"name": "B", "station": "A", "lat": -36.9, "lon": 174.4}],
                   "placeNames": [{"name": "C", "station": "A", "lat": -37.0, "lon": 176.5}]}, open(self.ref, "w"))

    def test_outputs_and_encoding(self):
        ds = sources.synthetic()
        ds["hs"][2, 9, 11] = np.nan  # (-37.75, 174.75), next to point A  # a missing step must stay null, never 0
        stats = build.build(ds, self.ref, self.tmp)
        root = os.path.join(self.tmp, "v1")
        meta = json.load(open(os.path.join(root, "meta.json")))
        self.assertEqual(meta["schema"], 1)
        self.assertEqual(meta["dataLicence"], "CC-BY-4.0")
        self.assertIn("CC BY 4.0", meta["credit"])
        self.assertEqual(len(meta["times"]), 8)
        self.assertEqual(meta["times"][1] - meta["times"][0], 3 * 3600)
        cells = json.load(open(os.path.join(root, "cells.json")))
        self.assertEqual(len(cells["lat"]), stats["cells"])
        self.assertTrue(all(lo < 175.0 for lo in cells["lon"]), "land cells must not be published")
        tile_files = os.listdir(os.path.join(root, "tiles"))
        self.assertEqual(len(tile_files), stats["tiles"])
        found_null = False
        for name in tile_files:
            t = json.load(open(os.path.join(root, "tiles", name)))
            for c in t["cells"]:
                self.assertEqual(name, f"{math.floor(c['lat'])}_{math.floor(c['lon'])}.json")
                self.assertTrue(all(v in (100, None) for v in c["hs"]))
                self.assertTrue(all(v == 80 for v in c["per"]))
                if None in c["hs"]:
                    found_null = True
        self.assertTrue(found_null)
        # The inland point (176.5E) still gets its nearest sea cell, ~>40 km away.
        self.assertGreater(stats["point_to_cell_km_max"], 40)

    def test_locations_format_matches_reference_format(self):
        loc = os.path.join(self.tmp, "locations.json")
        json.dump({"locations": [["A", -37.8, 174.8, "tide-station"], ["B", -36.9, 174.4, "coastal-spot"],
                                 ["C", -37.0, 176.5, "place"]]}, open(loc, "w"))
        np.testing.assert_array_equal(build.load_points(loc), build.load_points(self.ref))

    def test_antimeridian_crop(self):
        import xarray as xr
        lon = np.arange(0, 360, 0.5)
        lat = np.arange(-60, -20, 0.5)
        ds = xr.Dataset({"hs": (("time", "lat", "lon"), np.ones((1, lat.size, lon.size)))},
                        coords={"time": [np.datetime64("2026-11-24")], "lat": lat, "lon": lon})
        out = sources._crop_nz(ds)
        self.assertTrue(((out.lon >= 165) | (out.lon <= -175)).all())
        self.assertTrue((out.lon < -176).any() and (out.lon > 179).any())  # Chatham side kept
        self.assertTrue(((out.lat >= -53.5) & (out.lat <= -28.5)).all())


if __name__ == "__main__":
    unittest.main()
