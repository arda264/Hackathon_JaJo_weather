"""Download archived (past) forecasts from the Open-Meteo Historical Forecast API.

The Historical Forecast API serves the forecasts each weather model actually
issued at the time (short lead times, stitched together), which is exactly what
we need to learn how much to trust each model: we compare what the models *said*
against what ERA5 later *measured*.

Models fetched (all free, no API key):
    ecmwf_ifs025                     ECMWF IFS 0.25 deg
    gfs_global                       NOAA GFS
    icon_eu                          DWD ICON-EU
    meteofrance_arpege_europe        Meteo-France ARPEGE Europe
    knmi_harmonie_arome_netherlands  KNMI HARMONIE-AROME (Netherlands domain)
    ukmo_global_deterministic_10km   UK Met Office global 10 km

Points are ERA5 grid points inside geometry/area_of_interest.geojson (southern
North Sea corridor), so the truth extraction later needs no interpolation.

Writes one long-format CSV: forecast_blend/data/forecasts.csv
    time (UTC), lat, lon, then u/v components in m/s per model
    (converted from the API's speed/direction so we can blend vectors).

Run from the repository root:
    python forecast_blend/fetch_forecasts.py
"""

import time as _time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

API = "https://historical-forecast-api.open-meteo.com/v1/forecast"

MODELS = {
    "ecmwf_ifs025": "ecmwf",
    "gfs_global": "gfs",
    "icon_eu": "icon",
    "meteofrance_arpege_europe": "arpege",
    "knmi_harmonie_arome_netherlands": "harmonie",
    "ukmo_global_deterministic_10km": "ukmo",
}

# ERA5 0.25 deg grid points inside the area of interest (lat, lon)
POINTS = [(52.0, 2.5), (52.0, 4.0), (52.5, 3.0), (53.0, 3.5)]

START, END = "2024-07-02", "2026-08-13"
OUTDIR = Path(__file__).parent / "data"


def fetch_model_point(model, lat, lon, retries=4):
    params = dict(
        latitude=lat, longitude=lon,
        start_date=START, end_date=END,
        hourly="wind_speed_10m,wind_direction_10m",
        wind_speed_unit="ms", timezone="GMT", models=model,
    )
    for attempt in range(retries):
        r = requests.get(API, params=params, timeout=120)
        if r.status_code == 200:
            h = r.json()["hourly"]
            return pd.DataFrame({
                "time": pd.to_datetime(h["time"]),
                "speed": np.array(h["wind_speed_10m"], dtype="float64"),
                "direction": np.array(h["wind_direction_10m"], dtype="float64"),
            })
        wait = 5 * (attempt + 1)
        print(f"    HTTP {r.status_code}, retrying in {wait}s ...")
        _time.sleep(wait)
    raise RuntimeError(f"failed to fetch {model} at ({lat},{lon}): HTTP {r.status_code}")


def to_uv(speed, direction):
    """Meteorological direction (blowing FROM, deg) + speed -> u, v components."""
    rad = np.deg2rad(direction)
    return -speed * np.sin(rad), -speed * np.cos(rad)


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    frames = []
    for lat, lon in POINTS:
        base = None
        for model, short in MODELS.items():
            print(f"fetching {model} at ({lat}, {lon}) ...")
            df = fetch_model_point(model, lat, lon)
            u, v = to_uv(df["speed"].to_numpy(), df["direction"].to_numpy())
            part = pd.DataFrame({"time": df["time"], f"u_{short}": u, f"v_{short}": v})
            base = part if base is None else base.merge(part, on="time", how="outer")
            _time.sleep(1)  # stay polite on the free tier
        base.insert(1, "lat", lat)
        base.insert(2, "lon", lon)
        frames.append(base)

    out = pd.concat(frames, ignore_index=True).sort_values(["time", "lat", "lon"])
    path = OUTDIR / "forecasts.csv"
    out.to_csv(path, index=False)

    n = len(out)
    print(f"\nwrote {path}  ({n} rows, {out.time.min()} .. {out.time.max()})")
    for short in MODELS.values():
        missing = out[f"u_{short}"].isna().mean() * 100
        print(f"  {short:10s} missing: {missing:.2f}%")


if __name__ == "__main__":
    main()
