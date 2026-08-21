"""Schematic map of dummy candidate routes, Lowestoft -> IJmuiden.

The route family is parameterised exactly as in make_slides.py: a single
number, the lateral bulge in nm, applied as a smooth sinusoidal offset that
is zero at both ends and peaks at mid-course. Positive is north.

Coastlines and wind-farm footprints are hand-digitised approximations for
orientation only -- NOT for navigation.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

FIG = "slides/figures"
INK = "#1F2933"
MUTED = "#7B8794"
ACCENT = "#0B6E6E"
WARM = "#C0632C"
LAND = "#EDE6DA"
LANDEDGE = "#C9BCA6"
SEA = "#F7FAFB"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Calibri", "DejaVu Sans"],
    "text.color": INK,
    "axes.labelcolor": INK,
    "axes.edgecolor": MUTED,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "figure.facecolor": "white",
    "font.size": 11,
})

# ------------------------------------------------------------------ endpoints
LOWESTOFT = (52.4730, 1.7530)      # harbour entrance
IJMUIDEN = (52.4620, 4.5350)       # between the breakwaters
LAT0 = 0.5 * (LOWESTOFT[0] + IJMUIDEN[0])
COSLAT = np.cos(np.radians(LAT0))


def to_local(lat, lon):
    """Lat/lon -> local tangent-plane nm (east, north) about Lowestoft."""
    return ((np.asarray(lon) - LOWESTOFT[1]) * 60.0 * COSLAT,
            (np.asarray(lat) - LOWESTOFT[0]) * 60.0)


def to_ll(e, n):
    """Local nm (east, north) -> lat/lon."""
    return (LOWESTOFT[0] + np.asarray(n) / 60.0,
            LOWESTOFT[1] + np.asarray(e) / (60.0 * COSLAT))


E1, N1 = to_local(*IJMUIDEN)
L_RHUMB = float(np.hypot(E1, N1))
along = np.array([E1, N1]) / L_RHUMB
perp = np.array([-along[1], along[0]])        # 90 deg left of track = north-ish
BEARING = (np.degrees(np.arctan2(along[0], along[1]))) % 360.0


def route(bulge_nm, n=400):
    """Smooth sinusoidal-bulge route. Returns (lat, lon, length_nm)."""
    s = np.linspace(0.0, 1.0, n)
    off = bulge_nm * np.sin(np.pi * s)
    e = along[0] * s * L_RHUMB + perp[0] * off
    nn = along[1] * s * L_RHUMB + perp[1] * off
    length = float(np.sum(np.hypot(np.diff(e), np.diff(nn))))
    lat, lon = to_ll(e, nn)
    return lat, lon, length


# ----------------------------------------------- approximate coastlines (!!)
UK_COAST = [(52.98, 1.66), (52.83, 1.69), (52.71, 1.72), (52.61, 1.73),
            (52.53, 1.75), (52.4730, 1.7530), (52.40, 1.73), (52.32, 1.68),
            (52.24, 1.64), (52.13, 1.61), (52.06, 1.55), (52.02, 1.51),
            (51.95, 1.44)]
NL_COAST = [(53.05, 4.75), (52.96, 4.76), (52.88, 4.71), (52.80, 4.68),
            (52.71, 4.65), (52.62, 4.63), (52.53, 4.59), (52.4620, 4.5350),
            (52.40, 4.54), (52.34, 4.53), (52.27, 4.48), (52.20, 4.42),
            (52.14, 4.34), (52.10, 4.28), (52.02, 4.16)]

# Indicative offshore wind farm footprints, with hand-placed labels:
# (lat0, lon0, lat1, lon1, label, label_lon, label_lat, ha, va)
FARMS = [
    (52.34, 4.06, 52.46, 4.24, "Luchterduinen", 4.04, 52.40, "right", "center"),
    (52.22, 3.98, 52.36, 4.20, "Hollandse Kust Zuid", 4.09, 52.195, "center", "top"),
    (52.52, 4.14, 52.65, 4.29, "Prinses Amalia", 4.12, 52.585, "right", "center"),
    (52.63, 4.28, 52.76, 4.44, "Hollandse Kust Noord", 4.36, 52.785, "center", "bottom"),
    (52.57, 4.36, 52.65, 4.47, "Egmond aan Zee", 4.50, 52.61, "left", "center"),
    (52.17, 2.36, 52.33, 2.66, "East Anglia ONE", 2.70, 52.225, "left", "center"),
    (52.61, 1.76, 52.69, 1.83, "Scroby Sands", 1.86, 52.65, "left", "center"),
]

# --------------------------------------------------------------------- plot
BULGES = [-10, -5, 0, 5, 10, 15]
shades = plt.cm.viridis(np.linspace(0.08, 0.86, len(BULGES)))

fig, ax = plt.subplots(figsize=(11.4, 5.5))
ax.set_facecolor(SEA)

for coast, xfill in ((UK_COAST, 1.0), (NL_COAST, 5.4)):
    la = [p[0] for p in coast]
    lo = [p[1] for p in coast]
    ax.fill_betweenx(la, lo, xfill, color=LAND, zorder=1)
    ax.plot(lo, la, color=LANDEDGE, lw=1.2, zorder=2)

for la0, lo0, la1, lo1, name, tlo, tla, tha, tva in FARMS:
    ax.add_patch(Rectangle((lo0, la0), lo1 - lo0, la1 - la0,
                           facecolor="#9FB8C4", edgecolor="#6E8894",
                           alpha=0.42, lw=0.8, hatch="///", zorder=3))
    ax.text(tlo, tla, name, fontsize=7.4, color="#4A6673",
            ha=tha, va=tva, zorder=4)

def clipped_farms(lat, lon):
    """Which indicative farm footprints does this track pass through?"""
    hit = []
    for la0, lo0, la1, lo1, name, *_ in FARMS:
        inside = (lat >= la0) & (lat <= la1) & (lon >= lo0) & (lon <= lo1)
        if inside.any():
            hit.append(name)
    return hit


rows = []
for bulge, col in zip(BULGES, shades):
    lat, lon, length = route(bulge)
    hits = clipped_farms(lat, lon)
    lead = bulge == 0
    tag = "  CLIPS" if hits else ""
    ax.plot(lon, lat, color=col, lw=2.6 if lead else 1.9,
            ls="-" if lead else (0, (5, 2)),
            alpha=0.35 if hits else 1.0, zorder=6,
            label="{:+3d} nm bulge   {:.1f} nm{}".format(bulge, length, tag))
    rows.append((bulge, length, length / 18.0 * 60.0, hits))

for (la, lo), name, dx in ((LOWESTOFT, "Lowestoft", -0.06), (IJMUIDEN, "IJmuiden", 0.06)):
    ax.plot(lo, la, "o", ms=8, mfc="white", mec=INK, mew=2.0, zorder=8)
    ax.text(lo + dx, la - 0.075, name, fontsize=11, weight="bold", color=INK,
            ha="right" if dx < 0 else "left", zorder=8)

ax.annotate("", xy=(3.6, 52.468), xytext=(2.7, 52.468),
            arrowprops=dict(arrowstyle="-|>", color=MUTED, lw=1.2), zorder=7)
ax.text(3.15, 52.494, "{:.0f} nm on {:03.0f} T".format(L_RHUMB, BEARING),
        fontsize=9.5, color=MUTED, ha="center", zorder=7)

ax.set_xlim(1.30, 4.95)
ax.set_ylim(51.93, 53.05)
ax.set_aspect(1.0 / COSLAT)
ax.set_xlabel("Longitude (deg E)")
ax.set_ylabel("Latitude (deg N)")
ax.set_title("Candidate route family, Lowestoft to IJmuiden",
             fontsize=13, color=INK, loc="left", pad=10)
ax.grid(color="#E3EAED", lw=0.7, zorder=0)
leg = ax.legend(loc="lower left", frameon=True, fontsize=8.6, ncol=2,
                title="lateral bulge (positive = north)", title_fontsize=8.6)
leg.get_frame().set_edgecolor("#DCE3E6")
leg.get_frame().set_alpha(0.94)
fig.text(0.012, 0.015,
         "Schematic. Coastlines and wind-farm footprints are approximate, for orientation only "
         "- not for navigation.",
         fontsize=8.5, color=MUTED, style="italic")
fig.tight_layout(rect=(0, 0.035, 1, 1))
fig.savefig(FIG + "/s0_routemap.png", dpi=200)
plt.close(fig)

print("Lowestoft {:.4f} N {:.4f} E   ->   IJmuiden {:.4f} N {:.4f} E".format(
    LOWESTOFT[0], LOWESTOFT[1], IJMUIDEN[0], IJMUIDEN[1]))
print("rhumb line: {:.1f} nm on {:.1f} deg true".format(L_RHUMB, BEARING))
print("TWD for 150 TWA on starboard: {:.0f} deg true".format((BEARING + 150) % 360))
print()
print(" bulge    length     time @18kt   penalty   clips indicative zone")
for b, ln, mins, hits in rows:
    print("  {:+3d} nm   {:6.1f} nm   {:3.0f} min      {:+5.1f} nm   {}".format(
        b, ln, mins, ln - L_RHUMB, ", ".join(hits) if hits else "-"))
print()
print("saved " + FIG + "/s0_routemap.png")
