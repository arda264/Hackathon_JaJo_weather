# route — record-attempt routing

Route optimiser, robustness suite, and LLM brief for the Lowestoft → IJmuiden
record attempt. Formerly the standalone `dutchsail_route` repo; merged into
DutchSail as a subtree, so its full commit history is in this repo's log.

The **web front end lives at `frontend/route.html`**, as a subpage of the
DutchSail site — not here. This directory is the pipeline that feeds it.
See `CLAUDE.md` for the method, the course facts, and the hard-won gotchas.

## Run

All commands from the **repository root**.

```sh
python route/route.py --self-test          # sanity checks
python route/route.py route/input.json     # optimise against forecast/*.grb2 (needs pygrib)
python route/robustness.py --self-test     # fast sanity checks
python route/robustness.py --synthetic     # full synthetic run, no pygrib (~6 min)
python route/export_sample_route.py        # refresh frontend/data/route-sample.json
```

`robustness.py` writes `route/app/gribs/robustness.json`; `route.py` writes one
JSON per GRIB into the same directory. Both are read by `frontend/route.html`.

To view the page, serve the repo root and open `/frontend/route.html`:

```sh
python -m http.server 8000
```

The **Update route** control needs the live optimiser at `/api/route`, which only
exists on the deployed site. Served locally the page falls back to the stored
sample route and says so in a banner.

## LLM brief

`main.py` builds one `pydantic_ai.Agent` from `prompts/system_prompt.j2` and runs
it with `prompts/task_prompt.j2` filled in. Edit the `.j2` files or the
`question`/`preferences` in `main.py` to try things out.

```sh
pip install -r route/requirements.txt
```

Set your key in `.env` at the repo root:

```
OPENAI_API_KEY=sk-...
```

Then `python route/main.py`. The step is optional — the rest runs without a key.

## Deploy

Deployment is configured at the repo root, not here. The root `vercel.json`
serves the whole repo statically and builds `route/api/index.py` as a Python
function, rewriting `/api/route` onto it. `includeFiles` ships `route.py`,
`polars.json`, and `forecast/grib.grb2` into the function bundle;
`api/requirements.txt` pins its one dependency, `pygrib`.

```sh
curl -X POST https://YOUR_PROJECT.vercel.app/api/route \
  -H 'Content-Type: application/json' \
  -d '{"current":{"speed":1,"toward":45}}'
```

**Unverified:** `pygrib` is a heavy native dependency (ECCODES) and has not been
confirmed to build in the Vercel Python runtime. If it does not, this endpoint
fails and `frontend/route.html` falls back to the stored sample route.

## Facts worth keeping

The fixed course is `(52.471314, 1.767940)` → `(52.465867, 4.535065)`. Wind is
sampled from `forecast/grib.grb2` at each route position and time; boat speeds
come from `polars.json`. The input JSON carries only `current`, whose direction
is where the water flows **toward**. Output includes each sampled wind vector as
`wind_vectors` in knots. If no route reaches the finish within `MAX_HOURS`, the
closest partial route is returned with `reached_destination: false` and its
`remaining_nm`.
