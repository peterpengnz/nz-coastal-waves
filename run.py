#!/usr/bin/env python3
"""Fetch the latest NZ wave forecast and write static JSON.

  python run.py --source ecmwf --refdata refdata.json --out site
  python run.py --source copernicus ...            (needs COPERNICUSMARINE_SERVICE_* env)
  python run.py ... --published-meta URL           (exit early if that run is already live)

Exit code 0 also when skipped; prints a one-line JSON summary for CI logs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

from wavepipe import build, sources


def published_run(url: str) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.load(r).get("run")
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=sorted(sources.SOURCES), default="ecmwf")
    ap.add_argument("--refdata", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--hours", type=int, default=168)
    ap.add_argument("--published-meta", help="URL of the live meta.json; skip if its run is current")
    args = ap.parse_args()

    t0 = time.time()
    if args.published_meta and args.source == "ecmwf":
        from ecmwf.opendata import Client
        latest = Client().latest(type="fc", stream="wave", param="swh", step=0)
        live = published_run(args.published_meta)
        if live and live.startswith(latest.strftime("%Y-%m-%dT%H:%M")):
            print(json.dumps({"skipped": True, "run": live}))
            return 0
    ds = sources.SOURCES[args.source](hours=args.hours)
    t1 = time.time()
    stats = build.build(ds, args.refdata, args.out)
    stats.update(run=ds.attrs["run"], provider=ds.attrs["provider"], fetch_s=round(t1 - t0, 1), build_s=round(time.time() - t1, 1))
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
