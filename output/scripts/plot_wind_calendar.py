"""Day-by-day calendar of qualifying sailing days, one figure per corridor.

Each cell is one calendar day:
    0  grey   condition not met
    1  green  met, but an isolated day
    1  blue   met, and part of a run of >=2 consecutive qualifying days

Runs of consecutive days are drawn as one merged block with no internal gap, so
back-to-back stretches read as bars even without colour - the digit and the
merged shape are both secondary encodings alongside hue.

Reads output/results/wind_window_days_daily.csv (written by wind_window_days.py).
"""

import calendar

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyBboxPatch

DAILY = "output/results/wind_window_days_daily.csv"
FIGDIR = "output/figures"
DPI = 200
SCALE = DPI / 96.0

REGIONS = ["100%", "75%", "50%"]
MONTH_LETTERS = "JFMAMJJASOND"
YEAR_GAP = 0.8  # blank columns between year blocks

CRITERION = "18–30 kt from 205–235° or 305–335°, ≥6 consecutive hours, every cell at once"
SOURCE = ("ERA5 hourly 10 m wind (u10/v10), 0.25° grid at 52.5°N · criterion met simultaneously "
          "by every grid cell in the corridor · 2021-01-01 to 2026-08-14")

THEMES = {
    "light": dict(surface="#fcfcfb", primary="#0b0b0b", secondary="#52514e", muted="#898781",
                  empty="#f0efec", met="#008300", b2b="#2a78d6"),
    "dark": dict(surface="#1a1a19", primary="#ffffff", secondary="#c3c2b7", muted="#898781",
                 empty="#2c2c2a", met="#008300", b2b="#3987e5"),
}


def style(t):
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
        "figure.facecolor": t["surface"],
        "axes.facecolor": t["surface"],
        "savefig.facecolor": t["surface"],
    })


def relative_luminance(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ink_on(fill, t):
    return "#ffffff" if relative_luminance(fill) < 0.42 else t["primary"]


def cell(ax, x, y0, y1, fill, pad, r):
    """Rounded block covering rows y0..y1 (inclusive) of column x."""
    ax.add_patch(FancyBboxPatch(
        (x + pad, y0 + pad), 1 - 2 * pad, (y1 - y0 + 1) - 2 * pad,
        boxstyle=f"round,pad=0,rounding_size={r}",
        facecolor=fill, edgecolor="none", mutation_aspect=1, zorder=3))


def runs_of(flags):
    """Yield (start, end) inclusive index pairs of consecutive True values."""
    start = None
    for i, v in enumerate(flags):
        if v and start is None:
            start = i
        elif not v and start is not None:
            yield start, i - 1
            start = None
    if start is not None:
        yield start, len(flags) - 1


def draw(region, df, mode):
    t = THEMES[mode]
    style(t)

    sub = df[df.region == region].set_index("date")
    met = sub["met"].astype(bool)
    b2b = sub["back_to_back"].astype(bool)
    years = sorted({d.year for d in sub.index})

    total_x = len(years) * 12 + (len(years) - 1) * YEAR_GAP
    fig_w = 18.0
    side = (fig_w - 0.40) / total_x           # square cell, in inches
    grid_h = side * 31
    header, band, foot = 1.95, 0.55, 0.35
    fig_h = header + band + grid_h + foot

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=DPI)
    ax = fig.add_axes([0.30 / fig_w, foot / fig_h,
                       1 - 0.40 / fig_w, grid_h / fig_h])
    ax.set_xlim(0, total_x)
    ax.set_ylim(31, 0)
    ax.set_aspect("equal")
    ax.axis("off")

    px = total_x / (ax.get_position().width * fig_w * DPI)  # data units per device px
    pad = 1.0 * SCALE * px
    r = min(4.0 * SCALE * px, 0.5 - pad)

    # label bands sit just above the grid, not inside the header block
    y_year = 1 - (header + band - 0.42) / fig_h
    y_month = 1 - (header + band - 0.15) / fig_h

    for yi, year in enumerate(years):
        x0 = yi * (12 + YEAR_GAP)
        fig.text((ax.get_position().x0
                  + (x0 + 6) / total_x * ax.get_position().width),
                 y_year, str(year), ha="center", va="center",
                 fontsize=11, fontweight="600", color=t["primary"])

        for mi in range(12):
            x = x0 + mi
            n = calendar.monthrange(year, mi + 1)[1]
            dates = pd.date_range(f"{year}-{mi + 1:02d}-01", periods=n, freq="D")
            present = np.array([d in met.index for d in dates])
            if not present.any():
                continue

            fig.text((ax.get_position().x0 + (x + 0.5) / total_x * ax.get_position().width),
                     y_month, MONTH_LETTERS[mi],
                     ha="center", va="center", fontsize=7.5, color=t["muted"])

            m = np.array([bool(met[d]) if p else False for d, p in zip(dates, present)])
            bb = np.array([bool(b2b[d]) if p else False for d, p in zip(dates, present)])

            # not-met days: individual muted cells carrying a 0
            for i in np.where(present & ~m)[0]:
                cell(ax, x, i, i, t["empty"], pad, r)
                ax.text(x + 0.5, i + 0.5, "0", ha="center", va="center",
                        fontsize=6.2, color=t["muted"], zorder=4)

            # met days: merge each consecutive stretch into one block
            for a, b in runs_of(m):
                fill = t["b2b"] if (b > a or bb[a]) else t["met"]
                cell(ax, x, a, b, fill, pad, r)
                for i in range(a, b + 1):
                    ax.text(x + 0.5, i + 0.5, "1", ha="center", va="center",
                            fontsize=6.2, fontweight="600", color=ink_on(fill, t), zorder=4)

    for d in range(0, 31, 5):
        ax.text(-0.35, d + 0.5, str(d + 1), ha="right", va="center",
                fontsize=6.5, color=t["muted"])

    # --- header ---------------------------------------------------------------
    fig.text(0.012, 1 - 0.30 / fig_h, f"Qualifying sailing days · {region} corridor",
             ha="left", va="center", fontsize=15, fontweight="600", color=t["primary"])
    fig.text(0.012, 1 - 0.62 / fig_h, f"One cell per day. {CRITERION}.",
             ha="left", va="center", fontsize=9.5, color=t["secondary"])

    n_met, n_b2b = int(met.sum()), int(b2b.sum())
    keys = [(t["empty"], "0", "not met", t["muted"]),
            (t["met"], "1", "met — isolated day", None),
            (t["b2b"], "1", "met — back-to-back (≥2 days)", None)]
    x = 0.012
    for fill, digit, label, digit_ink in keys:
        fig.patches.append(FancyBboxPatch(
            (x, 1 - 1.02 / fig_h - 0.008), 0.0105, 0.016,
            boxstyle="round,pad=0,rounding_size=0.004", transform=fig.transFigure,
            facecolor=fill, edgecolor="none", zorder=5))
        fig.text(x + 0.00525, 1 - 1.02 / fig_h, digit, ha="center", va="center",
                 fontsize=6.2, fontweight="600",
                 color=digit_ink or ink_on(fill, t), zorder=6)
        fig.text(x + 0.016, 1 - 1.02 / fig_h, label, fontsize=8.5,
                 color=t["secondary"], va="center")
        x += 0.016 + len(label) * 0.0043 + 0.022

    fig.text(0.012, 1 - 1.40 / fig_h,
             f"{n_met} qualifying days in {len(met)} · {n_b2b} of them back-to-back "
             f"· longest streak {max((b - a + 1) for a, b in runs_of(met.to_numpy())) if n_met else 0} days",
             fontsize=9, color=t["primary"], va="center")

    fig.text(0.012, 0.14 / fig_h, SOURCE, ha="left", va="center",
             fontsize=7.5, color=t["muted"])

    out = f"{FIGDIR}/wind_window_calendar_{region.rstrip('%')}_{mode}.png"
    fig.savefig(out, dpi=DPI)
    plt.close(fig)
    return out, n_met, n_b2b


if __name__ == "__main__":
    df = pd.read_csv(DAILY, parse_dates=["date"])
    for mode in ("light", "dark"):
        for region in REGIONS:
            out, n_met, n_b2b = draw(region, df, mode)
            print(f"  {out}   met={n_met} back-to-back={n_b2b}")
