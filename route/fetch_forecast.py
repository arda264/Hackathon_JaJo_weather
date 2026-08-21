#!/usr/bin/env python3
"""Download the latest GFS 10 m wind forecast for the Lowestoft -> IJmuiden corridor.

NOAA's NOMADS filter endpoint serves a subsetted GRIB2 per forecast hour: just
u10/v10 over our bounding box, a few hundred bytes each. The hourly files are
concatenated into one GRIB2 (the format is a stream of self-describing messages,
so concatenation is a valid file) which xarray/cfgrib reads as a `step` dimension.

No API key. Cycles publish roughly 4 h after their nominal time, so the newest
usable cycle is found by walking backwards until one answers with GRIB bytes.

    python route/fetch_forecast.py              # newest cycle, 13 hours
    python route/fetch_forecast.py --hours 24
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import requests

NOMADS = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
FORECAST_DIR = Path(__file__).resolve().parent / "forecast"
GRIB_OUT = FORECAST_DIR / "gfs_latest.grb2"
META_OUT = FORECAST_DIR / "cycle.json"

# corridor bounding box, padded around the 52.47 N / 1.77 E -> 4.54 E rhumb line
BBOX = {"toplat": 53.5, "bottomlat": 51.5, "leftlon": 1.0, "rightlon": 5.0}
DEFAULT_HOURS = 13          # route.py's MAX_HOURS is 10; a little headroom
MIN_USABLE_HOURS = 8        # below this the routing window is too short to bother
CYCLE_LAG_HOURS = 4         # NOMADS publishes a cycle ~4 h after its nominal time


def _params(day: str, cycle: int, hour: int) -> dict:
    return {
        "dir": f"/gfs.{day}/{cycle:02d}/atmos",
        "file": f"gfs.t{cycle:02d}z.pgrb2.0p25.f{hour:03d}",
        "var_UGRD": "on",
        "var_VGRD": "on",
        "lev_10_m_above_ground": "on",
        "subregion": "",
        **BBOX,
    }


def fetch_hour(session: requests.Session, day: str, cycle: int, hour: int) -> bytes | None:
    """One forecast hour, or None if NOMADS does not have it yet."""
    try:
        r = session.get(NOMADS, params=_params(day, cycle, hour), timeout=90)
    except requests.RequestException as err:
        print(f"  f{hour:03d}: request failed ({err})", file=sys.stderr)
        return None
    if r.status_code != 200 or not r.content.startswith(b"GRIB"):
        return None
    return r.content


def latest_cycle(session: requests.Session, search_back_hours: int = 30) -> tuple[str, int]:
    """Newest cycle whose f000 is actually published."""
    now = dt.datetime.now(dt.timezone.utc)
    for back in range(0, search_back_hours, 6):
        t = now - dt.timedelta(hours=back + CYCLE_LAG_HOURS)
        day, cycle = t.strftime("%Y%m%d"), (t.hour // 6) * 6
        if fetch_hour(session, day, cycle, 0):
            return day, cycle
    raise RuntimeError(f"no published GFS cycle found in the last {search_back_hours} h")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=int, default=DEFAULT_HOURS,
                    help=f"forecast hours to fetch, f000..f<hours-1> (default {DEFAULT_HOURS})")
    args = ap.parse_args()

    session = requests.Session()
    day, cycle = latest_cycle(session)
    print(f"GFS cycle {day} {cycle:02d}z")

    chunks, got = [], []
    for hour in range(args.hours):
        blob = fetch_hour(session, day, cycle, hour)
        if blob is None:
            print(f"  f{hour:03d}: not available, stopping")
            break
        chunks.append(blob)
        got.append(hour)

    if len(got) < MIN_USABLE_HOURS:
        raise SystemExit(
            f"only {len(got)} forecast hours available, need {MIN_USABLE_HOURS}; "
            "leaving the existing forecast in place"
        )

    FORECAST_DIR.mkdir(parents=True, exist_ok=True)
    GRIB_OUT.write_bytes(b"".join(chunks))
    reference = dt.datetime.strptime(f"{day}{cycle:02d}", "%Y%m%d%H").replace(tzinfo=dt.timezone.utc)
    META_OUT.write_text(json.dumps({
        "cycle": reference.isoformat(),
        "hours": got,
        "source": "NOAA GFS 0.25 deg via NOMADS",
        "bbox": BBOX,
        "fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }, indent=2) + "\n")
    print(f"{len(got)} hours, {GRIB_OUT.stat().st_size:,} bytes -> {GRIB_OUT}")


if __name__ == "__main__":
    main()
