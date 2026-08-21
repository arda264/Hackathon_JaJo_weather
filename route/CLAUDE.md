# dutchsail_route

Post-processing and LLM-judgment suite for a sailing record attempt,
**Lowestoft → IJmuiden**. Hackathon project.

**Merged into DutchSail.** This was a standalone repo; it now lives at `route/`
inside the DutchSail weather repo, brought in as a git subtree so its history is
preserved in the log. Paths in this file are relative to `route/`, and the shell
blocks below assume `cd route`. Two things moved out: the web app is now
`frontend/route.html` (a subpage of the DutchSail site, rewritten in that site's
vanilla-JS style — `app/index.html` is gone), and Vercel config is now the root
`vercel.json` (`route/vercel.json` is gone). `app/gribs/` stays put as the
pipeline's output directory, and the frontend reads it from there.

Three teams. Two others own the **input-space builder** (perturbed GRIBs +
currents) and the **route optimiser**. We own everything downstream:
robustness analysis, sensitivity, ranking, and the LLM-written brief.

## Status

`robustness.py` is the MVP robustness suite and runs end to end. `route.py`
(from main) is the optimiser. `slides/` is pitch material built on a toy
model, separate from the pipeline. Still missing: real input-space builder
(currently a placeholder nested for-loop), exclusion zones, and an LLM layer
pointed at the KPIs rather than at wind min/avg/max.

## The course (fixed, durable facts)

| | |
|---|---|
| Start | Lowestoft, 52.4730 N, 1.7530 E |
| Finish | IJmuiden, 52.4620 N, 4.5350 E |
| Rhumb line | **101.7 nm on 090 T** — almost exactly due east |
| Target | **18 kt average → record ≈ 339 min** (5 h 39) |
| Operating point | ~20 kt TWS at 150 TWA → **TWD ≈ 240 T (WSW)** on starboard |

Single gybe-free reach. No tacks, no gybes, no meaningful detours. The whole
route family collapses to **one parameter: lateral bulge north of the rhumb
line, in nm.** Bulging north costs distance but rotates the heading, which
protects TWA when the wind backs — that distance-vs-angle trade is the only
real tactical decision on the course.

**The corridor is narrow and north-only.** Indicative wind-farm footprints
leave roughly **0 to +8 nm** usable: bulge south and you are in Luchterduinen
(and East Anglia ONE by −10 nm); bulge past ~+8 nm and you are in Prinses
Amalia. Nearly all the constraint is in the last 25 nm off the Dutch coast.

## Agreed method

1. **Input space** — perturb polar, TWS, TWD, current. Each axis gets discrete
   levels and a marginal weight; joint weight = product of marginals, so "one
   thing off" outranks "everything off".
2. **Optimise** — one input scenario in, one optimal route out.
3. **Cross-evaluate** — `T[i][j]` = elapsed time sailing route *i* when input
   *j* actually happens. Hold **geographic track** fixed and re-integrate the
   timing (a skipper commits to a course, not a schedule).
4. **Decide** — `P(break record) = Σ_j w_j · 1[T[i][j] < 339]`. Rank on this.
   The duration-vs-robustness Pareto front is **explanatory only**: the record
   time is the exchange rate between the two KPIs, so no hand trade-off needed.
5. **LLM layer** — narrates the distribution and writes the brief. It does
   *not* choose the route and does not do go/no-go. Every claim cites a
   scenario or metric ID so it can be checked.

## Gotchas — these are hard-won, do not re-derive

**Uniform polar scaling cannot discriminate between routes.** For fixed
geometry `T = ∫ds/V`, so scaling the polar by *k* scales every route's time by
exactly `1/k` and the ranking never moves. Polar scaling answers "can we do
it"; only TWD rotation and start-time offset answer "which route".

**Do not time-shift the currents with the wind.** Tides are astronomically
known; wind is a forecast. Shifting the wind field = forecast error (wind only
re-phases). Shifting the start time = a decision (both re-phase).

**Polars live in the water frame; GRIB wind is over ground.** Compute
`W_water = W_ground − V_current`, derive TWS/TWA from that, then add the
current vector back for the ground track. With 2+ kt streams here, skipping
this is a several-percent error on elapsed time.

**Masthead readings are not comparable to GRIB 10 m wind.** Use the team's
`wind_conv` (DNV-RP-C205 eq. 2.3.2.11) from the `hatchlings` repo
(`src/hatchlings/dnv_wind_conversion.py`) — do not reinvent it. A 20 kt
masthead reading at 20 m on a 1-min mean is ~**15.2 kt** at 10 m / 1-hour
mean: a ~24% systematic offset, larger than the whole ±10% polar sweep. Skip
it and every scenario looks wrong in the same direction, so any likelihood
comparison stops discriminating on weather pattern. Also check which height
**the polar** is referenced to — same bug, second bite. `t2` is
model-dependent (ERA5 ≈ 1 h @ 10 m, CFSR ≈ 10 min @ 10 m) so it belongs in
scenario metadata.

**Watch the denominator.** Percentages over *scenarios* are meaningful.
Percentages over *routes* describe the upstream team's sampling density, not
the world. Always label which.

**Exclude the diagonal.** Route *i* was optimised for input *i*, so `T[i][i]`
is the column minimum by construction. Including it gives every route one
flattering result and inflates robustness unequally. Report out-of-sample.

**Generation is expensive, evaluation is nearly free.** Optimise on a coarse
set of the most probable scenarios, then evaluate against a fine grid. The
matrix should be tall and thin (M ≫ N). A 5-axis × 5-level grid is 3,125
optimisations — infeasible; as re-evaluations, trivial.

**Independence holds across axes, not within the wind.** Polar × current ×
wind is fine, but TWS and TWD errors inside one forecast are correlated, and
multi-model spread already bundles that. Using multi-model spread *and*
independent TWS/TWD perturbations double-counts the same uncertainty.

**Two regimes where P(win) stops discriminating.** If P ≈ 1 everywhere,
maximise expected margin. If P ≈ 0 everywhere, maximise the *right tail* —
you need luck anyway, so variance becomes a friend and the "safe" route is
strictly worse.

**If the live nowcast-reweighting idea gets built** (observe TWS/TWD, reweight
scenarios — a particle filter over a fixed scenario set): σ must represent
*representativeness* error not instrument precision (σ_TWS ≈ 2 kt, σ_TWD ≈
10°), TWD is circular so use shortest angular difference, successive
observations are strongly autocorrelated so update every 30–60 min rather
than every 5, and monitor `ESS = 1/Σw²` — below ~20% of the scenario count,
say so instead of presenting a posterior built on three survivors.

## Robustness suite

```
python robustness.py --self-test              # fast sanity checks
python robustness.py --synthetic --quick      # fast APPROXIMATE run (~30 s)
python robustness.py --synthetic              # full synthetic, no pygrib (~6 min)
python robustness.py                          # against forecast/*.grb2 (needs pygrib)
```

N scenarios -> N optimised routes -> N x N cross-evaluation -> KPIs, written
to `app/gribs/robustness.json`. Axes: weather source, weather time shift
(model phase error), uniform polar scale. Weights are the product of
per-axis marginals. `--quick` uses a smaller beam and a coarser scenario grid
for iteration; drop it for the real run.

### Hard-won facts about route.py

**These change with route.py's tuning -- re-check after a merge.** The main
team retuned it (turn limit 20->2 deg, heading step 5->1 deg, MAX_HOURS 72->10,
ARRIVAL_NM 1->0.5, BEAM_WIDTH 500->1000). robustness.py no longer overrides
these -- it respects route.py's constants and only appends the true
destination as a final leg so every route covers the same course. `--beam`
and `--arrival-nm` override on demand.

**One beam search is ~22 s at BEAM_WIDTH 1000** (the current default), vs ~2 s
at beam 100 under the old tuning. That is why the full synthetic run is ~6 min
and `--quick` (beam 150, coarse grid) is ~30 s. Same 5.000 h / 16-leg answer
in the nominal case.

**MAX_HOURS is the orbiting backstop -- keep it tight.** The search steps
~6.7 nm at 20 kt, and the 2 deg/step turn limit gives a turning radius of
roughly `6.7 / (2 sin 1 deg)` = ~190 nm, so once inside that radius pointing
the wrong way the boat physically cannot turn to hit the 0.5 nm mark. Under
the old MAX_HOURS=72 this produced 197-leg, 65-hour, 292 nm orbit routes;
MAX_HOURS=10 now converts that into a clean RuntimeError instead. Infeasible
cells are the honest signal; do not "fix" them by widening ARRIVAL_NM.

**Optimiser and re-evaluator agree to 0.37%** (+1.1 min on a 5 h route), the
difference being the optimiser's final partial step. Small, and it only
touches the diagonal, which the KPIs exclude anyway. Re-verify on real GRIBs:
a spatially lumpy field samples differently between the optimiser's stepping
and the re-evaluator's leg-geometry walk.

**Polar reuse saves ~Nx and is approximate, not exact.** Uniform scaling does
not change the optimal heading, but a faster boat covers a 20-minute step
further and lands in different pruning cells, so geometry differs slightly.
The error is discretisation, not physics. `--exact-routes` disables it.

**The analysis inherits the optimiser's variance.** When some scenarios yield
clean 15-leg routes and others yield poor ones, part of the resulting
"robustness" ranking is really search quality, not route fragility. Check
path length vs the rhumb line before trusting a row.

**Never give a synthetic test field an unbounded trend.** A linear TWS ramp is
an exploit, not weather: the optimiser stalls for hours to collect more
breeze, and the ramp walks off the end of the polar table (58 kt vs a 40 kt
table). `synthetic_wind` clamps both trends.

**P(win) saturates when every scenario sits in the fruitful window.** With all
scenarios at 20 kt in the good TWD band, every route beat the target and the
KPI could not rank anything. `kpis()` also reports `margin_min`, and the CLI
falls back to ranking on margin when the P(win) spread is under 2 points.

## Repo

```
route.py                 # the optimiser (beam search over headings)
robustness.py            # scenarios, cross-evaluation, KPIs
export_sample_route.py   # one route -> ../frontend/data/route-sample.json
api/index.py             # /api/route endpoint, deployed by the root vercel.json
main.py, prompts/        # the LLM brief
app/gribs/               # pipeline output, read by ../frontend/route.html
slides/plot_routes.py    # route map + wind-farm clip check
slides/make_slides.py    # toy model, 3 figures, 4-slide pitch deck
slides/build.py          # runs both, in order
```

Build: `python slides/build.py` → `slides/robust_routing_pitch.pptx`
(4 slides, ~45 s each, speaker notes in the notes pane, ≈3.0 min total).

## Environment

Micromamba env `default_python` (3.13), **no `pip`**. Install with:

```
uv pip install --python /c/Micromamba/envs/default_python/python.exe <pkg>
```

`python-pptx`, `matplotlib`, `numpy` are installed. A project-local `.venv`
was declined — do not create one.

## Known debt / unverified

- Wind-farm footprints in `plot_routes.py` are **hand-digitised
  approximations**. The qualitative finding (narrow, north-only, pinched near
  the Dutch coast) is solid; the specific ±nm thresholds are not. Replace with
  Noordzeeloket or EMODnet geodata.
- The toy polar is a Gaussian in TWA, not the boat. Check whether the real
  polar has a planing/foiling **cliff** near 20 kt — if so, a linearised
  sensitivity will lie, and TWS perturbation (not polar scaling) is what
  exposes it.
- `HALF_NM` in `make_slides.py` duplicates the value `plot_routes.py` derives
  from the coordinates. Move an endpoint and you must change both.
- **The deck's closing line is unverified.** It claims the binding constraint
  is the wind farm, resting on the toy optimum (+7.5 nm) landing near the
  corridor edge (+8 nm). That agreement is partly coincidence. Re-check with
  real polars before pitching it: the optimum may sit well inside the corridor
  (constraint not binding, line wrong) or well outside (hard clamp, line
  stronger).
