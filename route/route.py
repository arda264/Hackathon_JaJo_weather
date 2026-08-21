#!/usr/bin/env python3
"""Minimal weather-routing scaffold (all speeds in knots, angles true degrees).

Input JSON:
{
  "current": {"speed": 1, "toward": 45}
}
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
from dataclasses import dataclass
from pathlib import Path

EARTH_RADIUS_NM = 3440.065
DEFAULT_START = (52.471314, 1.767940)
DEFAULT_DESTINATION = (52.465867, 4.535065)
MAX_HEADING_CHANGE_DEGREES = 2
STEP_MINUTES = 20
HEADING_STEP_DEGREES = 1
MAX_HOURS = 10
ARRIVAL_NM = 0.5
BEAM_WIDTH = 1000
POLARS_PATH = Path(__file__).with_name("polars.json")
FORECAST_DIR = Path(__file__).with_name("forecast")
GRIB_PATH = FORECAST_DIR / "grib.grb2"
GRIB_OUTPUT_DIR = Path(__file__).with_name("app") / "gribs"
METRES_PER_SECOND_TO_KNOTS = 1.943844


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float


@dataclass(frozen=True)
class State:
    point: Point
    hours: float
    route: tuple[Point, ...]
    heading: int | None = None


def angular_difference(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def distance_nm(a: Point, b: Point) -> float:
    lat1, lat2 = map(math.radians, (a.lat, b.lat))
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(h)))


def move(point: Point, east_nm: float, north_nm: float) -> Point:
    lat = point.lat + math.degrees(north_nm / EARTH_RADIUS_NM)
    cos_lat = max(1e-9, abs(math.cos(math.radians(point.lat))))
    lon = point.lon + math.degrees(east_nm / (EARTH_RADIUS_NM * cos_lat))
    return Point(lat, lon)


def interpolate(x: float, values: list[tuple[float, float]]) -> float:
    if x <= values[0][0]:
        return values[0][1]
    if x >= values[-1][0]:
        return values[-1][1]
    for (x0, y0), (x1, y1) in zip(values, values[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    raise AssertionError("unreachable")


def polar_speed(polars: dict[str, dict[str, float]], wind_speed: float, twa: float) -> float:
    tables = sorted(
        (float(tws), sorted((float(a), float(s)) for a, s in angles.items()))
        for tws, angles in polars.items()
    )
    return max(0.0, interpolate(wind_speed, [(tws, interpolate(twa, table)) for tws, table in tables]))


def load_polars(path: Path = POLARS_PATH) -> dict[str, dict[str, float]]:
    data = json.loads(path.read_text())
    if not isinstance(data.get("polar"), dict) or not data["polar"]:
        raise ValueError(f"{path} must contain a non-empty 'polar' object")
    return data["polar"]


def load_wind(path: Path = GRIB_PATH):
    import pygrib

    components = {}
    with pygrib.open(str(path)) as messages:
        for message in messages:
            if message.shortName in {"10u", "10v"}:
                components.setdefault(message.validDate, {})[message.shortName] = message

    frames = []
    for valid_time, pair in sorted(components.items()):
        if pair.keys() >= {"10u", "10v"}:
            latitudes, longitudes = pair["10u"].latlons()
            frames.append((valid_time, pair["10u"].values, pair["10v"].values, latitudes[:, 0], longitudes[0]))
    if not frames:
        raise ValueError(f"{path} contains no paired 10u/10v wind fields")

    start_time = frames[0][0]
    hours = [(frame[0] - start_time).total_seconds() / 3600 for frame in frames]

    def wind_at(point: Point, elapsed_hours: float) -> tuple[float, float, float, float]:
        if not hours[0] <= elapsed_hours <= hours[-1]:
            raise ValueError(f"route time {elapsed_hours:.1f}h is outside the GRIB forecast")
        upper = min(bisect.bisect_left(hours, elapsed_hours), len(hours) - 1)
        lower = max(0, upper - 1)
        latitudes, longitudes = frames[lower][3], frames[lower][4]
        row = abs(latitudes - point.lat).argmin()
        lon = point.lon % 360
        column = abs((longitudes - lon + 180) % 360 - 180).argmin()
        fraction = 0 if upper == lower else (elapsed_hours - hours[lower]) / (hours[upper] - hours[lower])
        u = frames[lower][1][row, column] + fraction * (frames[upper][1][row, column] - frames[lower][1][row, column])
        v = frames[lower][2][row, column] + fraction * (frames[upper][2][row, column] - frames[lower][2][row, column])
        u_knots = float(u) * METRES_PER_SECOND_TO_KNOTS
        v_knots = float(v) * METRES_PER_SECOND_TO_KNOTS
        speed = math.hypot(u_knots, v_knots)
        wind_from = math.degrees(math.atan2(-u, -v)) % 360
        return speed, wind_from, u_knots, v_knots

    # ponytail: nearest spatial grid point; add bilinear interpolation when 0.25-degree precision is insufficient.
    return wind_at


def route(data: dict, polars: dict[str, dict[str, float]] | None = None, wind_at=None) -> State:
    start = Point(*DEFAULT_START)
    destination = Point(*DEFAULT_DESTINATION)
    current_speed = float(data["current"]["speed"])
    current_toward = float(data["current"]["toward"])
    polars = polars or load_polars()
    wind_at = wind_at or load_wind()
    step_hours = STEP_MINUTES / 60
    heading_step = HEADING_STEP_DEGREES
    max_hours = MAX_HOURS
    arrival_nm = ARRIVAL_NM
    beam_width = BEAM_WIDTH
    max_heading_change = MAX_HEADING_CHANGE_DEGREES

    if step_hours <= 0 or heading_step <= 0 or 360 % heading_step or beam_width <= 0:
        raise ValueError("step_minutes and beam_width must be positive; heading_step must divide 360")
    if not 0 <= max_heading_change <= 180:
        raise ValueError("max_heading_change must be between 0 and 180 degrees")
    if not polars:
        raise ValueError("polars must not be empty")

    frontier = [State(start, 0.0, (start,))]
    best = frontier[0]
    steps = math.ceil(max_hours / step_hours)
    current_rad = math.radians(current_toward)

    for _ in range(steps):
        candidates: list[State] = []
        for state in frontier:
            wind_speed, wind_from, _, _ = wind_at(state.point, state.hours)
            headings = range(0, 360, heading_step)
            if state.heading is not None:
                headings = (h for h in headings if angular_difference(h, state.heading) <= max_heading_change)
            for heading in headings:
                boat_speed = polar_speed(polars, wind_speed, angular_difference(heading, wind_from))
                heading_rad = math.radians(heading)
                east = (boat_speed * math.sin(heading_rad) + current_speed * math.sin(current_rad)) * step_hours
                north = (boat_speed * math.cos(heading_rad) + current_speed * math.cos(current_rad)) * step_hours
                point = move(state.point, east, north)
                candidate = State(point, state.hours + step_hours, state.route + (point,), heading)
                distance = distance_nm(point, destination)
                if distance < distance_nm(best.point, destination):
                    best = candidate
                if distance <= arrival_nm:
                    return candidate
                candidates.append(candidate)

        # ponytail: beam search is approximate; replace with full isochrone hulls for production forecasts.
        cell_size = max(arrival_nm, 0.5)
        cells: dict[tuple[int, int, int], State] = {}
        for candidate in sorted(candidates, key=lambda s: distance_nm(s.point, destination)):
            key = (
                round(candidate.point.lat * 60 / cell_size),
                round(candidate.point.lon * 60 * math.cos(math.radians(candidate.point.lat)) / cell_size),
                candidate.heading // heading_step,
            )
            cells.setdefault(key, candidate)
        frontier = sorted(cells.values(), key=lambda s: distance_nm(s.point, destination))[:beam_width]

    return best


def result_json(result: State, wind_at=None) -> dict:
    wind_at = wind_at or load_wind()
    remaining_nm = distance_nm(result.point, Point(*DEFAULT_DESTINATION))
    vectors = []
    for index, point in enumerate(result.route):
        elapsed_hours = index * STEP_MINUTES / 60
        speed, wind_from, u, v = wind_at(point, elapsed_hours)
        vectors.append({
            "lat": round(point.lat, 6),
            "lon": round(point.lon, 6),
            "elapsed_hours": round(elapsed_hours, 3),
            "u_knots": round(u, 3),
            "v_knots": round(v, 3),
            "speed_knots": round(speed, 3),
            "from_degrees": round(wind_from, 1),
        })
    return {
        "reached_destination": remaining_nm <= ARRIVAL_NM,
        "remaining_nm": round(remaining_nm, 3),
        "duration_hours": round(result.hours, 3),
        "route": [[round(p.lat, 6), round(p.lon, 6)] for p in result.route],
        "wind_vectors": vectors,
    }


def self_test() -> None:
    assert polar_speed(load_polars(), 10, 90) == 12.234
    speed, direction, u, v = load_wind()(Point(*DEFAULT_START), 0)
    assert speed > 0 and 0 <= direction < 360 and math.isclose(speed, math.hypot(u, v))
    partial = route(
        {"current": {"speed": 0, "toward": 0}},
        {"10": {"0": 0, "180": 0}},
        lambda point, hours: (10, 0, 0, 0),
    )
    assert partial.point == Point(*DEFAULT_START)


def route_forecasts(data: dict, forecast_dir: Path, output_dir: Path = GRIB_OUTPUT_DIR) -> None:
    forecasts = sorted(forecast_dir.glob("*.grb2"))
    if not forecasts:
        raise ValueError(f"{forecast_dir} contains no *.grb2 files")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for forecast in forecasts:
        wind_at = load_wind(forecast)
        output = f"{forecast.stem}.json"
        (output_dir / output).write_text(json.dumps(result_json(route(data, wind_at=wind_at), wind_at), indent=2) + "\n")
        outputs.append(output)
        print(f"{forecast.name} -> {output_dir / output}")
    (output_dir / "index.json").write_text(json.dumps(outputs, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, help="JSON containing the current vector")
    parser.add_argument("forecast", nargs="?", type=Path, default=FORECAST_DIR, help="GRIB2 file or folder")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("ok")
        return
    if not args.input:
        parser.error("input JSON is required")
    data = json.loads(args.input.read_text())
    if args.forecast.is_dir():
        route_forecasts(data, args.forecast)
        return
    wind_at = load_wind(args.forecast)
    print(json.dumps(result_json(route(data, wind_at=wind_at), wind_at), indent=2))


if __name__ == "__main__":
    main()
