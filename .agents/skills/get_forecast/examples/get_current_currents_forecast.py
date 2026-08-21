"""Download the current surface-currents forecast from Copernicus Marine.

Unlike get_currents_forecast.py (which uses hardcoded dates), this script
always requests the forecast starting from "now" through a configurable
number of forecast days ahead, using the same area/variables as
get_currents_forecast.py.

Uses the hourly-instantaneous 2D (surface) currents dataset
`cmems_mod_nws_phy-cur_anfc_1.5km-2D_PT1H-i`, which has no vertical/depth
dimension (replaces the older daily 3D `cmems_mod_nws_phy-uv_anfc_7km-3D_P1D-m`
dataset).

Run with the `copernicus` pixi environment, e.g.:
    pixi run -e copernicus python get_current_currents_forecast.py
"""

import argparse
import getpass
from datetime import datetime, timedelta
from pathlib import Path

import copernicusmarine

# Same bounding box as get_wave_forecast.py
MIN_LONGITUDE = 1.6701955318171018
MAX_LONGITUDE = 4.713201098204792
MIN_LATITUDE = 52.2187035064974
MAX_LATITUDE = 52.99847368288424

DATASET_ID = "cmems_mod_nws_phy-cur_anfc_1.5km-2D_PT1H-i"
VARIABLES = ["uo", "vo"]

CREDENTIALS_FILE = (
    Path(__file__).resolve().parent / "credentials" / ".copernicusmarine-credentials"
)


def ensure_credentials(credentials_file: Path = CREDENTIALS_FILE) -> Path:
    """Ensure a copernicusmarine credentials file exists, creating it if needed.

    If `credentials_file` is missing, prompt the user for their Copernicus
    Marine username/password and create it via `copernicusmarine.login`.
    """
    if credentials_file.exists():
        return credentials_file

    print(f"No credentials file found at {credentials_file}.")
    username = input("Copernicus Marine username: ").strip()
    password = getpass.getpass("Copernicus Marine password: ")

    credentials_file.parent.mkdir(parents=True, exist_ok=True)
    copernicusmarine.login(
        username=username,
        password=password,
        credentials_file=credentials_file,
        force_overwrite=True,
    )
    return credentials_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--forecast-days",
        type=float,
        default=6,
        help="Number of days ahead to download the forecast for (default: 6).",
    )
    parser.add_argument(
        "--output-directory",
        default="output/results",
        help="Directory to write the downloaded NetCDF file to (default: output/results).",
    )
    args = parser.parse_args()

    start_datetime = datetime.now()
    end_datetime = start_datetime + timedelta(days=args.forecast_days)

    start_str = start_datetime.strftime("%Y-%m-%dT%H:%M:%S")
    end_str = end_datetime.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"Downloading currents forecast from {start_str} to {end_str}")

    output_filename = f"currents_forecast_{start_datetime.strftime('%Y%m%dT%H%M%S')}.nc"

    credentials_file = ensure_credentials()

    copernicusmarine.subset(
        dataset_id=DATASET_ID,
        variables=VARIABLES,
        minimum_longitude=MIN_LONGITUDE,
        maximum_longitude=MAX_LONGITUDE,
        minimum_latitude=MIN_LATITUDE,
        maximum_latitude=MAX_LATITUDE,
        start_datetime=start_str,
        end_datetime=end_str,
        output_directory=args.output_directory,
        output_filename=output_filename,
        credentials_file=credentials_file,
    )


if __name__ == "__main__":
    main()
