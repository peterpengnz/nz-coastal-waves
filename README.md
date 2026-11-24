# nz-coastal-waves

Free, open wave forecasts for the New Zealand coast as small static JSON files,
rebuilt twice a day from open model data.

- **Code:** Apache-2.0 ([LICENSE](LICENSE), keep [NOTICE](NOTICE))
- **Data:** CC BY 4.0, commercial use allowed with attribution ([LICENSE-DATA.md](LICENSE-DATA.md))

## Sources

| `--source` | Model | Grid | Steps | Upstream licence | Account |
|---|---|---|---|---|---|
| `ecmwf` (default) | ECMWF IFS wave model, open data | 0.25° | 3 h to 144 h, then 6 h | CC BY 4.0 | none |
| `copernicus` | Météo-France MFWAM (Copernicus Marine `GLOBAL_ANALYSISFORECAST_WAV_001_027`) | 1/12° | 3 h, 10 days | Copernicus Marine Service licence (free, attribution) | free account |

`copernicus` is implemented but not yet verified against a live account.

## Output (schema 1)

```
v1/meta.json                    run, provider, model, grid, attribution, times (epoch s), maxMatchKm
v1/cells.json                   {"lat":[…], "lon":[…]} every published sea cell
v1/tiles/<floor(lat)>_<floor(lon)>.json
    {"run", "times", "cells":[{"lat","lon","hs":[cm],"dir":[deg from],"per":[0.1 s],
                               optional "hsSw","perSw","hsWw"}]}
```
Integers keep files small; `null` means no data (never 0). Directions are where
waves come **from**. Published cells: the nearest sea cell to every point in
`locations.json`, plus every sea cell within 40 km of one.

**Client recipe:** read `meta.json` → read `cells.json` (cache per `run`) → pick
the nearest cell (treat > `maxMatchKm` as "no wave forecast here") → read its
tile. Values are model output for an open-sea grid cell, which can be well
offshore; harbours are not resolved.

## Run locally

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests
.venv/bin/python run.py --source ecmwf --refdata locations.json --out site
python3 -m http.server -d site 8766
```
Typical run: ~65 MB download, ~3 min, ~0.5 GB peak memory; output ~0.5 MB.

## Automation

`.github/workflows/waves.yml` runs twice a day on GitHub Actions and deploys to
GitHub Pages. A run whose model cycle is already published exits in seconds.
For `copernicus`, set repository secrets `COPERNICUSMARINE_SERVICE_USERNAME` /
`COPERNICUSMARINE_SERVICE_PASSWORD` and the variable `WAVE_SOURCE=copernicus`.

## Disclaimer

Model forecasts only, not observations. Not for navigation or safety-of-life use.
