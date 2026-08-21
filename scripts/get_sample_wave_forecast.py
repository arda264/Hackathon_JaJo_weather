"""Download a 1-week sample wave forecast for sample data purposes.

Requests the wave forecast starting from "now" through 7 days ahead, using
the same area/dataset/variables as get_current_wave_forecast.py, and saves
the result to sample_forecast_data/ with today's date embedded in the
filename.

Run with the `copernicus` pixi environment, e.g.:
    pixi run -e copernicus python scripts/get_sample_wave_forecast.py
"""

import getpass
from datetime import datetime, timedelta
from pathlib import Path

import copernicusmarine

# Same bounding box as get_current_wave_forecast.py
MIN_LONGITUDE = 1.6701955318171018
MAX_LONGITUDE = 4.713201098204792
MIN_LATITUDE = 52.2187035064974
MAX_LATITUDE = 52.99847368288424

DATASET_ID = "cmems_mod_nws_wav_anfc_1.5km_PT1H-i"
VARIABLES = ["VMDR_SW1", "VTM01_SW1", "VHM0_SW1", "VHM0_WW", "VTM01_WW", "VMDR_WW"]

FORECAST_DAYS = 7

ROOT_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = ROOT_DIR / "credentials" / ".copernicusmarine-credentials"
OUTPUT_DIRECTORY = ROOT_DIR / "sample_forecast_data"


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
    # copernicusmarine 2.x quirks: login() writes to configuration_file_directory
    # (credentials_file only controls where subset() READS from), and it returns
    # False on bad credentials instead of raising — handle both
    ok = copernicusmarine.login(
        username=username,
        password=password,
        configuration_file_directory=credentials_file.parent,
        force_overwrite=True,
    )
    if ok is False or not credentials_file.exists():
        raise SystemExit(
            "Copernicus Marine login failed — no credentials file was written. "
            "Check the username/password and try again."
        )
    return credentials_file


def main():
    start_datetime = datetime.now()
    end_datetime = start_datetime + timedelta(days=FORECAST_DAYS)

    start_str = start_datetime.strftime("%Y-%m-%dT%H:%M:%S")
    end_str = end_datetime.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"Downloading wave forecast from {start_str} to {end_str}")

    output_filename = f"wave_forecast_{start_datetime.strftime('%Y%m%d')}.nc"

    credentials_file = ensure_credentials()

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    copernicusmarine.subset(
        dataset_id=DATASET_ID,
        variables=VARIABLES,
        minimum_longitude=MIN_LONGITUDE,
        maximum_longitude=MAX_LONGITUDE,
        minimum_latitude=MIN_LATITUDE,
        maximum_latitude=MAX_LATITUDE,
        start_datetime=start_str,
        end_datetime=end_str,
        output_directory=str(OUTPUT_DIRECTORY),
        output_filename=output_filename,
        credentials_file=credentials_file,
    )


if __name__ == "__main__":
    main()
