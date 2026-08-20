"""Learn per-forecast-model blend weights against ERA5 "real" wind data.

Six weather models' archived forecasts (fetched by ``fetch_forecasts.py`` from
the Open-Meteo Historical Forecast API) are compared with ERA5 hourly 10 m wind
(u10/v10) at the same grid points inside the area of interest. TWO weights are
learned per forecast model — one for wind speed, one for wind direction:

    speed:      s_blend = sum_m ws_m * s_m
    direction:  e_blend = sum_m wd_m * e_m ,  e_m = unit vector of model m's
                wind direction; the blended direction is the angle of e_blend

    ws_m, wd_m >= 0 ,  sum ws = sum wd = 1

Direction is circular, so it is blended through unit vectors (350 deg and
10 deg must average to 0 deg, not 180 deg); the weights are fit by least
squares on the unit-vector components against ERA5's unit vector. The simplex
constraint keeps every weight interpretable as "how much to trust model m".

Evaluation is honest: weights are fit on the first 75% of the record
(chronological) and every reported score is from the held-out final 25%,
compared against each individual model and the equal-weight ensemble.
Direction fitting/scoring uses only hours with ERA5 speed > 2 m/s, where a
direction is physically meaningful.

Outputs (forecast_blend/results/):
    weights.json      learned speed + direction weights and training metadata
    metrics.csv       per-source test metrics (speed RMSE/MAE/bias,
                      direction MAE)
    blend_evaluation_{light,dark}.png   weights + test-accuracy figure

Run from the repository root (after fetch_forecasts.py):
    python forecast_blend/train_blend.py
"""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from scipy.optimize import minimize

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).parent
GRIB = r"C:\Users\ardac\Desktop\wind_data\ERA5hourly10m.grib"
FORECASTS = HERE / "data" / "forecasts.csv"
TRUTH_CACHE = HERE / "data" / "era5_truth.csv"
RESULTS = HERE / "results"

POINTS = [(52.0, 2.5), (52.0, 4.0), (52.5, 3.0), (53.0, 3.5)]
TRAIN_FRACTION = 0.75
MIN_TRUTH_SPEED = 2.0  # m/s; below this a wind direction is meaningless

SOURCES = ["ecmwf", "gfs", "icon", "arpege", "harmonie", "ukmo"]
LONG_NAME = {
    "ecmwf": "ECMWF IFS 0.25°",
    "gfs": "NOAA GFS",
    "icon": "DWD ICON-EU",
    "arpege": "Météo-France ARPEGE",
    "harmonie": "KNMI HARMONIE-AROME",
    "ukmo": "UKMO Global 10 km",
}

DPI = 200
SCALE = DPI / 96.0

# design tokens shared with output/scripts/* (validated with the dataviz
# palette validator in both modes)
THEMES = {
    "light": dict(
        surface="#fcfcfb", primary="#0b0b0b", secondary="#52514e",
        muted="#898781", grid="#e1e0d9", axis="#c3c2b7",
        bar="#86b6ef", accent="#104281",
    ),
    "dark": dict(
        surface="#1a1a19", primary="#ffffff", secondary="#c3c2b7",
        muted="#898781", grid="#2c2c2a", axis="#383835",
        bar="#3987e5", accent="#9ec5f4",
    ),
}


# --- data --------------------------------------------------------------------
def load_truth():
    """ERA5 u10/v10 at the evaluation points, hourly, cached to CSV."""
    if TRUTH_CACHE.exists():
        return pd.read_csv(TRUTH_CACHE, parse_dates=["time"])

    import xarray as xr
    ds = xr.open_dataset(GRIB, engine="cfgrib", backend_kwargs={"indexpath": ""},
                         chunks={"time": 4000})
    lats = xr.DataArray([p[0] for p in POINTS], dims="point")
    lons = xr.DataArray([p[1] for p in POINTS], dims="point")
    pick = ds[["u10", "v10"]].sel(latitude=lats, longitude=lons)
    u = pick.u10.compute().values
    v = pick.v10.compute().values
    times = pd.DatetimeIndex(ds.time.values)

    frames = []
    for i, (lat, lon) in enumerate(POINTS):
        frames.append(pd.DataFrame({
            "time": times, "lat": lat, "lon": lon,
            "u_era5": u[:, i], "v_era5": v[:, i],
        }))
    truth = pd.concat(frames, ignore_index=True)
    truth.to_csv(TRUTH_CACHE, index=False)
    return truth


def load_merged():
    fc = pd.read_csv(FORECASTS, parse_dates=["time"])
    truth = load_truth()
    df = fc.merge(truth, on=["time", "lat", "lon"], how="inner")
    df = df.dropna().sort_values(["time", "lat", "lon"]).reset_index(drop=True)
    return df


# --- weight fitting ----------------------------------------------------------
def fit_simplex_weights(X, y):
    """Least squares over the probability simplex: w >= 0, sum w = 1."""
    n = X.shape[1]
    XtX, Xty = X.T @ X, X.T @ y

    def loss(w):
        return float(w @ XtX @ w - 2.0 * w @ Xty + y @ y)

    def grad(w):
        return 2.0 * (XtX @ w - Xty)

    res = minimize(
        loss, np.full(n, 1.0 / n), jac=grad, method="SLSQP",
        bounds=[(0.0, 1.0)] * n,
        constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0,
                      "jac": lambda w: np.ones_like(w)}],
        options={"maxiter": 500, "ftol": 1e-12},
    )
    if not res.success:
        raise RuntimeError(f"weight optimisation failed: {res.message}")
    w = np.clip(res.x, 0.0, None)
    return w / w.sum()


# --- angles ------------------------------------------------------------------
def speed(u, v):
    return np.hypot(u, v)


def direction_from(u, v):
    """Meteorological direction the wind blows FROM, degrees."""
    return (np.degrees(np.arctan2(-u, -v)) + 360.0) % 360.0


def unit_vectors(u, v):
    """(sin, cos) components of the FROM direction — safe near calm."""
    s = np.maximum(speed(u, v), 1e-9)
    return -u / s, -v / s


def angular_error(d1, d2):
    diff = np.abs(d1 - d2) % 360.0
    return np.minimum(diff, 360.0 - diff)


def blend_direction(sin_mat, cos_mat, w):
    """Weighted mean of unit vectors -> blended direction in degrees."""
    s, c = sin_mat @ w, cos_mat @ w
    return (np.degrees(np.arctan2(s, c)) + 360.0) % 360.0


# --- figure ------------------------------------------------------------------
def barh_panel(ax, t, names, values, fmt, xlabel, title, colors=None, xmax=None):
    y = np.arange(len(values))[::-1]
    ax.barh(y, values, height=0.62,
            color=colors if colors else t["bar"], edgecolor="none", zorder=3)
    xmax = xmax if xmax else max(values) * 1.22
    for yi, v in zip(y, values):
        ax.text(v + xmax * 0.015, yi, fmt.format(v), va="center", ha="left",
                fontsize=9, color=t["secondary"])
    ax.set_yticks(y, names, fontsize=9)
    ax.set_xlim(0, xmax)
    ax.xaxis.grid(True, color=t["grid"], linewidth=1.0 * SCALE)
    ax.set_axisbelow(True)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_title(title, fontsize=10.5, fontweight="600",
                 color=t["primary"], loc="left", pad=8)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)


def make_figure(ws, wd, metrics, split_time, n_train, n_test, mode):
    t = THEMES[mode]
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
        "figure.facecolor": t["surface"], "axes.facecolor": t["surface"],
        "savefig.facecolor": t["surface"], "text.color": t["primary"],
        "axes.labelcolor": t["secondary"], "xtick.color": t["muted"],
        "ytick.color": t["muted"], "axes.edgecolor": t["axis"],
        "axes.linewidth": 1.0 * SCALE,
        "xtick.major.size": 0, "ytick.major.size": 0,
    })

    fig, axes = plt.subplots(2, 2, figsize=(13.5, 9.6), dpi=DPI)
    fig.subplots_adjust(left=0.16, right=0.97, top=0.885, bottom=0.085,
                        wspace=0.42, hspace=0.42)

    for ax, w, what in ((axes[0, 0], ws, "speed"), (axes[0, 1], wd, "direction")):
        order = np.argsort(w)[::-1]
        barh_panel(ax, t, [LONG_NAME[SOURCES[i]] for i in order], w[order],
                   "{:.2f}", "learned weight",
                   f"Learned {what} weights", xmax=max(0.5, w.max() * 1.25))

    for ax, key, fmt, xlabel, title in (
        (axes[1, 0], "speed_rmse_ms", "{:.2f}",
         "wind-speed RMSE vs ERA5 (m/s), held-out test",
         "Held-out speed accuracy (lower is better)"),
        (axes[1, 1], "direction_mae_deg", "{:.1f}",
         "direction MAE vs ERA5 (deg), held-out test",
         "Held-out direction accuracy (lower is better)"),
    ):
        rows = [(LONG_NAME[s], metrics[s][key], False) for s in SOURCES]
        rows.append(("Equal-weight mean", metrics["equal"][key], False))
        rows.append(("Learned blend", metrics["blend"][key], True))
        rows.sort(key=lambda r: r[1])
        colors = [t["accent"] if hl else t["bar"] for _, _, hl in rows]
        barh_panel(ax, t, [r[0] for r in rows], [r[1] for r in rows],
                   fmt, xlabel, title, colors=colors)

    fig.text(0.012, 0.972, "Forecast-model blending against ERA5",
             fontsize=15, fontweight="600", color=t["primary"])
    fig.text(0.012, 0.940,
             "Two weights per model — speed blended directly, direction blended "
             "through unit vectors · non-negative, each set sums to 1 · "
             f"{len(POINTS)} North Sea points, hourly · train to "
             f"{split_time:%Y-%m-%d} ({n_train:,} samples), test after "
             f"({n_test:,} samples)",
             fontsize=9.5, color=t["secondary"])
    fig.text(0.012, 0.014,
             "Truth: ERA5 hourly u10/v10 · Forecasts: Open-Meteo Historical "
             "Forecast API (archived model runs) · highlighted bar: learned "
             f"blend · direction fit/scored on hours with ERA5 speed > "
             f"{MIN_TRUTH_SPEED:.0f} m/s",
             fontsize=7.5, color=t["muted"])

    RESULTS.mkdir(parents=True, exist_ok=True)
    fig.savefig(RESULTS / f"blend_evaluation_{mode}.png", dpi=DPI)
    plt.close(fig)


# --- main --------------------------------------------------------------------
def main():
    df = load_merged()
    print(f"merged dataset: {len(df):,} samples "
          f"({df.time.min()} .. {df.time.max()}, {len(POINTS)} points)")

    # chronological split so the test set is strictly in the future
    cut = df.time.quantile(TRAIN_FRACTION)
    train, test = df[df.time <= cut], df[df.time > cut]

    def speeds(part):
        return np.column_stack([speed(part[f"u_{s}"].to_numpy(),
                                      part[f"v_{s}"].to_numpy())
                                for s in SOURCES])

    def units(part):
        sin_cols, cos_cols = [], []
        for s in SOURCES:
            si, co = unit_vectors(part[f"u_{s}"].to_numpy(),
                                  part[f"v_{s}"].to_numpy())
            sin_cols.append(si)
            cos_cols.append(co)
        return np.column_stack(sin_cols), np.column_stack(cos_cols)

    # --- speed weights -------------------------------------------------------
    s_true_train = speed(train["u_era5"].to_numpy(), train["v_era5"].to_numpy())
    ws = fit_simplex_weights(speeds(train), s_true_train)

    # --- direction weights (unit vectors, windy hours only) ------------------
    windy_train = train[s_true_train > MIN_TRUTH_SPEED]
    sin_t, cos_t = units(windy_train)
    e_sin, e_cos = unit_vectors(windy_train["u_era5"].to_numpy(),
                                windy_train["v_era5"].to_numpy())
    wd = fit_simplex_weights(np.vstack([sin_t, cos_t]),
                             np.concatenate([e_sin, e_cos]))

    # --- held-out evaluation -------------------------------------------------
    s_true = speed(test["u_era5"].to_numpy(), test["v_era5"].to_numpy())
    d_true = direction_from(test["u_era5"].to_numpy(), test["v_era5"].to_numpy())
    windy = s_true > MIN_TRUTH_SPEED
    S = speeds(test)
    sin_m, cos_m = units(test)
    d_models = direction_from(-sin_m, -cos_m)  # per-model direction, degrees

    def score(s_pred, d_pred):
        err = s_pred - s_true
        return dict(
            speed_rmse_ms=float(np.sqrt(np.mean(err ** 2))),
            speed_mae_ms=float(np.mean(np.abs(err))),
            speed_bias_ms=float(np.mean(err)),
            direction_mae_deg=float(np.mean(
                angular_error(d_pred[windy], d_true[windy]))),
        )

    metrics = {}
    for i, s in enumerate(SOURCES):
        metrics[s] = score(S[:, i], d_models[:, i])
    eq = np.full(len(SOURCES), 1.0 / len(SOURCES))
    metrics["equal"] = score(S @ eq, blend_direction(sin_m, cos_m, eq))
    metrics["blend"] = score(S @ ws, blend_direction(sin_m, cos_m, wd))

    RESULTS.mkdir(parents=True, exist_ok=True)
    with open(RESULTS / "weights.json", "w") as f:
        json.dump({
            "speed_weights": {s: round(float(w), 6) for s, w in zip(SOURCES, ws)},
            "direction_weights": {s: round(float(w), 6)
                                  for s, w in zip(SOURCES, wd)},
            "sources": {s: LONG_NAME[s] for s in SOURCES},
            "constraint": "per set: w >= 0, sum(w) = 1",
            "speed_fit": "least squares, blended speed vs ERA5 speed",
            "direction_fit": ("least squares on direction unit vectors vs "
                              f"ERA5, hours with ERA5 speed > "
                              f"{MIN_TRUTH_SPEED} m/s"),
            "truth": "ERA5 hourly 10 m u/v",
            "points": POINTS,
            "train_until": str(cut),
            "n_train_hours": int(len(train)),
            "n_test_hours": int(len(test)),
        }, f, indent=2)

    mdf = pd.DataFrame(metrics).T
    mdf.index.name = "source"
    mdf.round(4).to_csv(RESULTS / "metrics.csv")

    for mode in ("light", "dark"):
        make_figure(ws, wd, metrics, cut, len(train), len(test), mode)

    print(f"\nlearned weights (train <= {cut:%Y-%m-%d %H:%M}):")
    print(f"  {'model':22s} {'speed':>7s} {'direction':>10s}")
    for i, s in enumerate(SOURCES):
        print(f"  {LONG_NAME[s]:22s} {ws[i]:7.3f} {wd[i]:10.3f}")

    print("\nheld-out test metrics (vs ERA5):")
    print(mdf.round(3).sort_values("speed_rmse_ms").to_string())

    best_s = min(SOURCES, key=lambda s: metrics[s]["speed_rmse_ms"])
    best_d = min(SOURCES, key=lambda s: metrics[s]["direction_mae_deg"])
    gain_s = (1 - metrics["blend"]["speed_rmse_ms"]
              / metrics[best_s]["speed_rmse_ms"]) * 100
    gain_d = (1 - metrics["blend"]["direction_mae_deg"]
              / metrics[best_d]["direction_mae_deg"]) * 100
    print(f"\nspeed blend vs best single ({LONG_NAME[best_s]}): "
          f"{gain_s:+.1f}% RMSE improvement (held-out)")
    print(f"direction blend vs best single ({LONG_NAME[best_d]}): "
          f"{gain_d:+.1f}% MAE improvement (held-out)")
    print(f"\nwrote {RESULTS}/weights.json, metrics.csv, "
          f"blend_evaluation_light.png, blend_evaluation_dark.png")


if __name__ == "__main__":
    main()
