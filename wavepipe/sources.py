"""Wave forecast sources. Each returns an xarray Dataset cropped to the NZ box with
dims (time, lat, lon), lon in [-180, 180), and variables (NaN = land / no data):

    hs   significant wave height, m (combined wind sea + swell)
    dir  mean wave direction, degrees FROM (meteorological convention)
    per  mean wave period, s
optional (Copernicus only):
    hs_sw  primary swell height, m      per_sw  primary swell period, s
    hs_ww  wind-wave height, m

plus attrs: provider, model, run (ISO UTC), grid_deg, attribution, licence.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile

import numpy as np
import xarray as xr

# NZ box incl. Raoul (Kermadecs), Chatham and the subantarctic islands.
LAT_MIN, LAT_MAX = -53.5, -28.5
LON_W, LON_E = 165.0, -175.0  # crosses the antimeridian


def _to_pm180(lon: xr.DataArray) -> xr.DataArray:
    return ((lon + 180) % 360) - 180


def _crop_nz(ds: xr.Dataset) -> xr.Dataset:
    ds = ds.assign_coords(lon=_to_pm180(ds.lon)).sortby("lon").sortby("lat")
    lat_ok = (ds.lat >= LAT_MIN) & (ds.lat <= LAT_MAX)
    lon_ok = (ds.lon >= LON_W) | (ds.lon <= LON_E)
    return ds.sel(lat=ds.lat[lat_ok], lon=ds.lon[lon_ok])


def ecmwf(hours: int = 168, workdir: str | None = None) -> xr.Dataset:
    """ECMWF open data, IFS wave model (stream=wave), 0.25°, 3-hourly. CC BY 4.0, no account."""
    from ecmwf.opendata import Client

    client = Client(source=os.environ.get("ECMWF_SOURCE", "ecmwf"))
    run = client.latest(type="fc", stream="wave", param="swh", step=0)
    # 06/18 UTC runs stop at 144 h; 00/12 UTC go further.
    max_step = 144 if run.hour in (6, 18) else 240
    # Open-data wave steps: 0–144 h every 3 h, then every 6 h (00/12 UTC runs only).
    limit = min(hours, max_step)
    steps = [s for s in range(0, min(limit, 144) + 1, 3)] + [s for s in range(150, limit + 1, 6)]
    work = workdir or tempfile.mkdtemp(prefix="ecmwf-wave-")
    target = os.path.join(work, "wave.grib2")
    client.retrieve(date=run, type="fc", stream="wave", param=["swh", "mwd", "mwp"], step=steps, target=target)
    ds = open_ecmwf_grib(target)
    ds.attrs.update(
        provider="ecmwf-opendata",
        model="ECMWF IFS wave model (stream=wave)",
        run=run.replace(tzinfo=dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        grid_deg=0.25,
        attribution="Contains ECMWF open data (CC BY 4.0).",
        licence="CC-BY-4.0",
    )
    return ds


def open_ecmwf_grib(path: str) -> xr.Dataset:
    """Reads the downloaded GRIB lazily, crops to NZ, THEN loads (global grid is ~1 GB in memory)."""
    raw = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    raw = raw.swap_dims({"step": "valid_time"})
    # `time` here is the model run time; drop it (and step/surface) before using valid_time as `time`.
    raw = raw.drop_vars([v for v in ("time", "step", "surface") if v in raw.variables])
    raw = raw.rename({"valid_time": "time", "latitude": "lat", "longitude": "lon", "swh": "hs", "mwd": "dir", "mwp": "per"})
    return _crop_nz(raw[["hs", "dir", "per"]]).load()


COPERNICUS_DATASET = "cmems_mod_glo_wav_anfc_0.083deg_PT3H-i"
COPERNICUS_VARS = {
    "VHM0": "hs", "VMDR": "dir", "VTM10": "per",
    "VHM0_SW1": "hs_sw", "VTM01_SW1": "per_sw", "VHM0_WW": "hs_ww",
}


def copernicus(hours: int = 168, workdir: str | None = None) -> xr.Dataset:
    """Copernicus Marine global waves (Météo-France MFWAM), 1/12°, 3-hourly.

    Needs COPERNICUSMARINE_SERVICE_USERNAME / COPERNICUSMARINE_SERVICE_PASSWORD
    (CI secrets). UNTESTED until an account exists — dataset/variable ids must be
    confirmed with `copernicusmarine describe` on first run.
    """
    import copernicusmarine as cm

    now = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    # Start 24 h back so "today" keeps its earlier hours (the product includes recent analysis).
    start = now - dt.timedelta(hours=now.hour % 3) - dt.timedelta(hours=24)
    end = start + dt.timedelta(hours=hours + 24)
    work = workdir or tempfile.mkdtemp(prefix="cmems-wave-")
    parts = []
    for i, (lo, hi) in enumerate([(LON_W, 179.99), (-180.0, LON_E)]):  # two requests across the antimeridian
        fname = f"part{i}.nc"
        cm.subset(
            dataset_id=COPERNICUS_DATASET,
            variables=list(COPERNICUS_VARS),
            minimum_longitude=lo, maximum_longitude=hi,
            minimum_latitude=LAT_MIN, maximum_latitude=LAT_MAX,
            start_datetime=start.isoformat(), end_datetime=end.isoformat(),
            output_directory=work, output_filename=fname, overwrite=True,
        )
        parts.append(xr.open_dataset(os.path.join(work, fname)))
    raw = xr.concat(parts, dim="longitude")
    ds = raw.rename({k: v for k, v in COPERNICUS_VARS.items() if k in raw}).rename(
        {"latitude": "lat", "longitude": "lon"}
    )
    ds = _crop_nz(ds[[v for v in COPERNICUS_VARS.values() if v in ds]]).load()
    ds.attrs.update(
        provider="copernicus-marine",
        model="Météo-France MFWAM (GLOBAL_ANALYSISFORECAST_WAV_001_027)",
        # The product has no single "model cycle" attribute we can rely on; the run id is the
        # retrieval window start (UTC, Z), which is unique per publish and sortable.
        run=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        grid_deg=1 / 12,
        attribution="Generated using E.U. Copernicus Marine Service Information; https://doi.org/10.48670/moi-00017",
        licence="Copernicus Marine Service licence",
    )
    return ds


SOURCES = {"ecmwf": ecmwf, "copernicus": copernicus}


def synthetic(n_steps: int = 8) -> xr.Dataset:
    """Tiny deterministic grid for unit tests (no network)."""
    lat = np.arange(-40.0, -35.0, 0.25)
    lon = np.arange(172.0, 177.0, 0.25)
    t = np.array([np.datetime64("2026-11-24T00:00") + np.timedelta64(3 * i, "h") for i in range(n_steps)])
    hs = np.full((n_steps, lat.size, lon.size), 1.0, dtype="float32")
    hs[:, :, lon >= 175.0] = np.nan  # "land" east of 175E
    ds = xr.Dataset(
        {"hs": (("time", "lat", "lon"), hs), "dir": (("time", "lat", "lon"), np.full_like(hs, 225.0)),
         "per": (("time", "lat", "lon"), np.full_like(hs, 8.0))},
        coords={"time": t, "lat": lat, "lon": lon},
    )
    ds.attrs.update(provider="synthetic", model="test", run="2026-11-24T00:00:00Z", grid_deg=0.25, attribution="test", licence="test")
    return ds
