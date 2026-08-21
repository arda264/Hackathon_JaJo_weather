#!/usr/bin/env python3
"""Robustness analysis over a perturbed input space (MVP).

Pipeline
--------
1. Build N scenarios by perturbing the inputs (placeholder nested for-loop).
2. Optimise one route per scenario  ->  N routes.          [the diagonal]
3. Re-evaluate every route under every scenario  ->  N x N. [the off-diagonal]
4. Reduce to KPIs: out-of-sample duration, spread, P(break record).

The point of step 3 is that step 2 alone tells you nothing about robustness:
a route optimised for scenario i is trivially good in scenario i. Robustness
only shows up when you sail route i through the *other* inputs.

Perturbation axes (per Scenario):
  weather           which GRIB / model run
  weather_shift_h   model phase error: the weather arrives early or late
  polar_scale       uniform boat-speed multiplier

Current is a constant vector for now (route.py has no current GRIB reader),
so it is an input, not a perturbation axis. evaluate_route already takes a
current_at(point, hours) callable, so a GRIB-backed reader drops straight in.

Caveats, deliberate for MVP
---------------------------
* evaluate_route holds the leg bearing as the boat's *water* heading and
  projects the resulting ground velocity onto the leg. Following a fixed
  ground track exactly means solving the current triangle for the heading;
  that is a refinement, not the MVP.
* Wind from GRIB is over ground; the polar wants wind over water. With ~1 kt
  of stream the error is small but real. See CLAUDE.md.
* Uniform polar scaling does not change the optimal geometry in a static
  field, so those scenarios produce near-duplicate routes by construction.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

import route as R

TARGET_AVG_KNOTS = 18.0


# --------------------------------------------------------------------- scenario
@dataclass(frozen=True)
class Scenario:
    """One point in the perturbed input space."""

    scenario_id: str
    weather: str                    # key into the wind-provider table
    weather_shift_h: float = 0.0    # + = weather arrives this many hours later
    polar_scale: float = 1.0        # uniform multiplier on boat speed
    weight: float = 1.0             # likelihood, normalised across the set

    def label(self) -> str:
        return "{} shift{:+.1f}h polar{:.2f}".format(
            self.weather, self.weather_shift_h, self.polar_scale)


def gaussian(x: float, sd: float) -> float:
    return math.exp(-0.5 * (x / sd) ** 2) if sd > 0 else (1.0 if x == 0 else 0.0)


def build_scenarios(
    weathers: list[str],
    weather_shifts: tuple[float, ...] = (-1.5, -0.75, 0.0, 0.75, 1.5),
    polar_scales: tuple[float, ...] = (0.95, 1.0, 1.05),
    sd_weather_shift: float = 1.0,
    sd_polar: float = 0.05,
    quick: bool = False,
) -> list[Scenario]:
    """Placeholder input-space builder: nested for-loop, product-of-marginals weights.

    Joint weight is the product of per-axis marginals, so 'one thing off'
    outranks 'everything off'. Weather choice is treated as uniform: the models
    are alternative hypotheses, not deviations from a nominal.
    """
    if quick:
        # Fewer weather shifts = fewer beam searches (polar scales are free via
        # reuse, so keep them for KPI resolution). Halves the search count.
        weather_shifts = (-1.0, 0.0, 1.0)
    out: list[Scenario] = []
    for n, (weather, ws, ps) in enumerate(
        itertools.product(weathers, weather_shifts, polar_scales)
    ):
        weight = gaussian(ws, sd_weather_shift) * gaussian(ps - 1.0, sd_polar)
        out.append(Scenario("s{:03d}".format(n), weather, ws, ps, weight))

    total = sum(s.weight for s in out) or 1.0
    return [replace(s, weight=s.weight / total) for s in out]


# ------------------------------------------------------------------- providers
def synthetic_wind(tws0: float, twd0: float, tws_rate: float = 0.0, twd_rate: float = 0.0,
                   tws_clamp: tuple[float, float] = (6.0, 30.0),
                   twd_clamp: float = 40.0):
    """Time-varying uniform wind field, so the shift axes actually bite.

    tws_rate in kt/h, twd_rate in deg/h (positive = veering). Both trends are
    CLAMPED: an unbounded linear ramp is not weather, it is an exploit -- the
    optimiser will happily stall for hours to collect more breeze, and the
    ramp walks off the end of the polar table. Real GRIBs are bounded, so the
    clamp is what makes the toy field behave like one.
    """

    def wind_at(point: R.Point, hours: float):
        speed = min(tws_clamp[1], max(tws_clamp[0], tws0 + tws_rate * hours))
        wind_from = (twd0 + max(-twd_clamp, min(twd_clamp, twd_rate * hours))) % 360
        radians = math.radians(wind_from)
        return speed, wind_from, -speed * math.sin(radians), -speed * math.cos(radians)

    return wind_at


def constant_current(speed: float, toward: float):
    """current_at(point, hours) -> (east_knots, north_knots). Constant for now.

    Signature is time-aware so a GRIB-backed tidal reader drops in unchanged.
    """

    def current_at(point: R.Point, hours: float):
        radians = math.radians(toward)
        return speed * math.sin(radians), speed * math.cos(radians)

    return current_at


def time_shifted(fn, shift_hours: float, lo: float | None = None, hi: float | None = None):
    """Wrap a (point, hours) provider so its field is sampled shift_hours earlier.

    Clamping is opt-in via lo/hi, for GRIB readers that raise outside their
    validity window. Do NOT clamp analytic fields: clamping at lo=0 would make
    a positive shift a no-op over the first shift_hours of the route, which is
    exactly where forecast phase error hurts most. For GRIBs the honest fix is
    a forecast window wider than the route plus the largest shift.
    """

    def shifted(point: R.Point, hours: float):
        t = hours - shift_hours
        if lo is not None:
            t = max(lo, t)
        if hi is not None:
            t = min(hi, t)
        return fn(point, t)

    return shifted


def scaled_polars(polars: dict, factor: float) -> dict:
    return {tws: {twa: speed * factor for twa, speed in angles.items()}
            for tws, angles in polars.items()}


# ------------------------------------------------------------------ evaluation
def bearing_deg(a: R.Point, b: R.Point) -> float:
    east = (b.lon - a.lon) * 60.0 * math.cos(math.radians(0.5 * (a.lat + b.lat)))
    north = (b.lat - a.lat) * 60.0
    return math.degrees(math.atan2(east, north)) % 360.0


def evaluate_route(route_points, wind_at, current_at, polars) -> float:
    """Hours to sail a FIXED track under one scenario. inf if it stalls.

    This is the off-diagonal of the matrix and the whole reason the analysis
    says anything about robustness.
    """
    hours = 0.0
    for start, end in zip(route_points, route_points[1:]):
        leg_nm = R.distance_nm(start, end)
        if leg_nm <= 1e-9:
            continue
        course = bearing_deg(start, end)
        wind_speed, wind_from, _, _ = wind_at(start, hours)
        boat = R.polar_speed(polars, wind_speed, R.angular_difference(course, wind_from))

        course_rad = math.radians(course)
        cur_e, cur_n = current_at(start, hours)
        # Hold the leg bearing as the water heading; project ground velocity
        # onto the leg. See module docstring.
        along = ((boat * math.sin(course_rad) + cur_e) * math.sin(course_rad)
                 + (boat * math.cos(course_rad) + cur_n) * math.cos(course_rad))
        if along <= 0.01:
            return math.inf
        hours += leg_nm / along
    return hours


def providers_for(scenario: Scenario, wind_table: dict, current_base, polars_base,
                  wind_bounds=(None, None)):
    """Materialise (wind_at, current_at, polars) for one scenario."""
    wind_at = time_shifted(wind_table[scenario.weather], scenario.weather_shift_h,
                           *wind_bounds)
    polars = scaled_polars(polars_base, scenario.polar_scale)
    return wind_at, current_base, polars


# ---------------------------------------------------------------------- matrix
def optimise_routes(scenarios, wind_table, current_base, polars_base, current_cfg,
                    reuse_polar: bool = True, wind_bounds=(None, None)):
    """One beam search per DISTINCT route-shaping scenario. Returns (routes, failures).

    Uniform polar scaling leaves the optimal heading unchanged in a static
    field, so with reuse_polar we search once per (weather, shift) and share
    the geometry across polar scales. Not exact -- a faster boat covers a
    20-minute step further and lands in different pruning cells -- but the
    error is discretisation, not physics, and it cuts searches by the number
    of polar levels. Pass reuse_polar=False to optimise every scenario.
    """
    routes, failures = [], []
    cache: dict = {}
    for scenario in scenarios:
        key = ((scenario.weather, scenario.weather_shift_h) if reuse_polar
               else scenario.scenario_id)
        if key not in cache:
            design = replace(scenario, polar_scale=1.0) if reuse_polar else scenario
            wind_at, _, polars = providers_for(design, wind_table, current_base,
                                               polars_base, wind_bounds)
            try:
                track = list(R.route(current_cfg, polars=polars, wind_at=wind_at).route)
                # The search stops within ARRIVAL_NM of the mark. Close the gap so
                # every route covers the same course; otherwise a loose arrival
                # tolerance flatters durations by up to ARRIVAL_NM / boatspeed.
                finish = R.Point(*R.DEFAULT_DESTINATION)
                if R.distance_nm(track[-1], finish) > 0.05:
                    track.append(finish)
                cache[key] = tuple(track)
            except (RuntimeError, ValueError) as exc:
                cache[key] = None
                failures.append((scenario.scenario_id, str(exc)[:70]))
        routes.append(cache[key])
    return routes, failures


def cross_evaluate(scenarios, routes, wind_table, current_base, polars_base):
    """T[i][j] = hours sailing route i when scenario j actually happens."""
    n = len(scenarios)
    T = [[math.inf] * n for _ in range(n)]
    materialised = [providers_for(s, wind_table, current_base, polars_base) for s in scenarios]
    for i, points in enumerate(routes):
        if points is None:
            continue
        for j, (wind_at, current_at, polars) in enumerate(materialised):
            T[i][j] = evaluate_route(points, wind_at, current_at, polars)
    return T


def kpis(scenarios, T, record_hours: float) -> list[dict]:
    """Out-of-sample KPIs: the diagonal is each route's own design case."""
    n = len(scenarios)
    rows = []
    for i in range(n):
        pairs = [(scenarios[j].weight, T[i][j]) for j in range(n)
                 if j != i and math.isfinite(T[i][j])]
        total = sum(w for w, _ in pairs)
        if not pairs or total <= 0:
            rows.append({"scenario_id": scenarios[i].scenario_id, "label": scenarios[i].label(),
                         "in_sample_h": T[i][i], "mean_h": None, "spread_h": None,
                         "p_win": None, "n_ok": 0})
            continue
        mean = sum(w * t for w, t in pairs) / total
        var = sum(w * (t - mean) ** 2 for w, t in pairs) / total
        p_win = sum(w for w, t in pairs if t < record_hours) / total
        rows.append({
            "margin_min": (record_hours - mean) * 60.0,
            "scenario_id": scenarios[i].scenario_id,
            "label": scenarios[i].label(),
            "in_sample_h": T[i][i],
            "mean_h": mean,
            "spread_h": math.sqrt(var),
            "p_win": p_win,
            "n_ok": len(pairs),
        })
    return rows


# ------------------------------------------------------------------------ main
def record_hours() -> float:
    nm = R.distance_nm(R.Point(*R.DEFAULT_START), R.Point(*R.DEFAULT_DESTINATION))
    return nm / TARGET_AVG_KNOTS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=Path("input.json"),
                        help="JSON with the current vector (default input.json)")
    parser.add_argument("--synthetic", action="store_true",
                        help="use built-in time-varying wind instead of GRIBs (no pygrib needed)")
    parser.add_argument("--forecast-dir", type=Path, default=R.FORECAST_DIR)
    parser.add_argument("--out", type=Path, default=Path("app/gribs/robustness.json"))
    parser.add_argument("--arrival-nm", type=float, default=None,
                        help="override route.py's ARRIVAL_NM (default: leave route.py's value)")
    parser.add_argument("--beam", type=int, default=None,
                        help="override route.py's BEAM_WIDTH (default: leave route.py's value)")
    parser.add_argument("--quick", action="store_true",
                        help="fast, APPROXIMATE run for iteration: smaller beam + coarser grid")
    parser.add_argument("--exact-routes", action="store_true",
                        help="optimise every scenario rather than sharing geometry across polar scales")
    args = parser.parse_args()

    if args.beam is not None:
        R.BEAM_WIDTH = args.beam
    elif args.quick:
        R.BEAM_WIDTH = 150   # ~7x faster than beam 1000; approximate geometry
    if args.arrival_nm is not None:
        R.ARRIVAL_NM = args.arrival_nm
    if args.quick:
        print("=" * 64)
        print("QUICK MODE: beam {}, coarse scenario grid. APPROXIMATE -- for".format(R.BEAM_WIDTH))
        print("iteration only. Drop --quick for the real run.")
        print("=" * 64)
    cfg = json.loads(args.input.read_text())
    polars_base = R.load_polars()
    current_base = constant_current(float(cfg["current"]["speed"]), float(cfg["current"]["toward"]))

    if args.synthetic:
        # Three "models" that disagree about the breeze, all inside the
        # a-priori-fruitful band (20 kt, TWD 190-225 -- see CLAUDE.md).
        wind_table = {
            "steady_205": synthetic_wind(20.0, 205.0),
            "veering_195": synthetic_wind(20.0, 195.0, tws_rate=0.0, twd_rate=3.0),
            "building_215": synthetic_wind(18.5, 215.0, tws_rate=0.6, twd_rate=-1.0),
        }
    else:
        gribs = sorted(args.forecast_dir.glob("*.grb2"))
        if not gribs:
            raise SystemExit("no *.grb2 in {}".format(args.forecast_dir))
        wind_table = {g.stem: R.load_wind(g) for g in gribs}

    scenarios = build_scenarios(sorted(wind_table), quick=args.quick)
    target = record_hours()
    print("scenarios {}   record {:.3f} h ({:.0f} min) at {:.0f} kt over {:.1f} nm".format(
        len(scenarios), target, target * 60, TARGET_AVG_KNOTS, target * TARGET_AVG_KNOTS))

    print("optimising routes (beam {}, arrival {} nm{}) ...".format(
        R.BEAM_WIDTH, R.ARRIVAL_NM, "" if args.exact_routes else ", polar geometry shared"))
    routes, failures = optimise_routes(scenarios, wind_table, current_base, polars_base, cfg,
                                       reuse_polar=not args.exact_routes)
    ok = sum(1 for r in routes if r is not None)
    print("  {}/{} scenarios have a route".format(ok, len(routes)))
    for sid, msg in failures[:5]:
        print("  FAILED {}: {}".format(sid, msg))

    print("cross-evaluating {0} x {0} ...".format(len(scenarios)))
    T = cross_evaluate(scenarios, routes, wind_table, current_base, polars_base)
    rows = kpis(scenarios, T, target)

    n = len(scenarios)
    infeasible = sum(1 for i in range(n) for j in range(n) if not math.isfinite(T[i][j]))
    finite = [T[i][j] for i in range(n) for j in range(n)
              if i != j and math.isfinite(T[i][j])]
    print("  cells {}  infeasible {} ({:.1%})  finite range {:.2f}-{:.2f} h".format(
        n * n, infeasible, infeasible / (n * n), min(finite), max(finite)))

    scored = [r for r in rows if r["p_win"] is not None]
    saturated = bool(scored) and (max(r["p_win"] for r in scored)
                                  - min(r["p_win"] for r in scored)) < 0.02
    if saturated:
        print()
        print("  NOTE  P(win) is {:.0%} for every route, so it cannot rank them. Ranking on"
              .format(scored[0]["p_win"]))
        print("        expected margin instead. This is the saturated regime: when the record")
        print("        is safe everywhere, maximise slack; when unreachable everywhere,")
        print("        maximise the best case rather than the mean.")
    ranked = sorted(scored, key=lambda r: -(r["margin_min"] if saturated else r["p_win"]))
    worst = ranked[-3:] if len(ranked) > 3 else []
    print()
    print("  {:<36} {:>9} {:>9} {:>8} {:>9} {:>7}".format(
        "scenario (design case)", "in-samp", "mean_oos", "spread", "margin", "P(win)"))
    for r in ranked[:12]:
        print("  {:<36} {:>8.2f}h {:>8.2f}h {:>7.2f}h {:>+7.1f}m {:>6.0%}".format(
            r["label"], r["in_sample_h"], r["mean_h"], r["spread_h"],
            r["margin_min"], r["p_win"]))
    if worst:
        print("  ... worst {}:".format(len(worst)))
        for r in worst:
            print("  {:<36} {:>8.2f}h {:>8.2f}h {:>7.2f}h {:>+7.1f}m {:>6.0%}".format(
                r["label"], r["in_sample_h"], r["mean_h"], r["spread_h"],
                r["margin_min"], r["p_win"]))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "record_hours": target,
        "target_avg_knots": TARGET_AVG_KNOTS,
        "scenarios": [{"scenario_id": s.scenario_id, "weather": s.weather,
                       "weather_shift_h": s.weather_shift_h,
                       "polar_scale": s.polar_scale, "weight": s.weight}
                      for s in scenarios],
        "matrix_hours": [[None if math.isinf(v) else round(v, 4) for v in row] for row in T],
        "kpis": rows,
    }, indent=2) + "\n")
    print("\nwrote {}".format(args.out))


def self_test() -> None:
    polars = R.load_polars()
    wind = synthetic_wind(20.0, 205.0)
    cur = constant_current(0.0, 0.0)

    # Straight rhumb line, uniform 20 kt at TWD 205 -> TWA 115, polar peak.
    a, b = R.Point(*R.DEFAULT_START), R.Point(*R.DEFAULT_DESTINATION)
    nm = R.distance_nm(a, b)
    hours = evaluate_route([a, b], wind, cur, polars)
    implied = nm / hours
    assert abs(implied - R.polar_speed(polars, 20.0, 115.0)) < 0.15, implied

    # Uniform polar scaling divides elapsed time by exactly the factor.
    slow = evaluate_route([a, b], wind, cur, scaled_polars(polars, 0.9))
    assert abs(slow * 0.9 - hours) < 1e-6, (slow, hours)

    # Time shift moves the sampled field, including at t=0 (no clamping).
    veer = synthetic_wind(20.0, 195.0, twd_rate=6.0)
    assert abs(time_shifted(veer, 1.0)(a, 0.0)[1] - (195.0 - 6.0)) < 1e-9
    assert abs(time_shifted(veer, -1.0)(a, 2.0)[1] - (195.0 + 18.0)) < 1e-9
    # Clamping, when asked for, pins the sample inside the window.
    assert time_shifted(veer, 1.0, lo=0.0)(a, 0.0)[1] == veer(a, 0.0)[1]

    print("ok  rhumb {:.1f} nm  {:.2f} h  {:.2f} kt implied".format(nm, hours, implied))


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
    else:
        main()
