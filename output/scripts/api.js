/* DutchSail weather — the data-access layer, in output/scripts with the rest
 * of the project's scripts.
 *
 * Every network request the site makes goes through this file; pages and
 * frontend/assets/common.js never call fetch() themselves. To change an
 * endpoint, a parameter, or a fallback order, change it here.
 *
 * Each page loads this first (as ../output/scripts/api.js), then
 * assets/common.js, both deferred (fetchMarine uses kmhToKt from common.js at
 * call time). Relative route URLs below resolve against the page in
 * frontend/, not against this file's location.
 */
"use strict";

/* ---------------- project data ---------------- */

// learned weights from forecast_blend/results/weights.json (train_until 2026-02-01)
const BLEND = {
  speed: { ecmwf: 0.350273, gfs: 0.238027, icon: 0.193598, arpege: 0.0, harmonie: 0.135443, ukmo: 0.082658 },
  direction: { ecmwf: 0.298035, gfs: 0.219159, icon: 0.272952, arpege: 0.047509, harmonie: 0.03144, ukmo: 0.130904 },
};

// fixed color assignment — color follows the entity, never its rank
const MODELS = [
  { key: "ecmwf", id: "ecmwf_ifs025", name: "ECMWF IFS 0.25°", color: "--s2" },
  { key: "gfs", id: "gfs_global", name: "NOAA GFS", color: "--s3" },
  { key: "icon", id: "icon_eu", name: "DWD ICON-EU", color: "--s4" },
  { key: "arpege", id: "meteofrance_arpege_europe", name: "ARPEGE Europe", color: "--s5" },
  { key: "harmonie", id: "knmi_harmonie_arome_netherlands", name: "KNMI HARMONIE", color: "--s6" },
  { key: "ukmo", id: "ukmo_global_deterministic_10km", name: "UKMO Global 10 km", color: "--s7" },
];
const BLEND_COLOR = "--s1";

// the four ERA5 grid points the blend was trained on (southern North Sea corridor)
const POINTS = [
  { lat: 52.5, lon: 3.0, name: "Mid-corridor (52.5°N 3.0°E)" },
  { lat: 52.0, lon: 2.5, name: "Western corridor (52.0°N 2.5°E)" },
  { lat: 52.0, lon: 4.0, name: "Off the Dutch coast (52.0°N 4.0°E)" },
  { lat: 53.0, lon: 3.5, name: "Northern corridor (53.0°N 3.5°E)" },
];

/* ---------------- endpoints ---------------- */

const OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast";
const MARINE_URL = "https://marine-api.open-meteo.com/v1/marine";

const ROUTE_TODAY_URL = "./data/route-today.json";     // rewritten daily by CI
const ROUTE_SAMPLE_URL = "./data/route-sample.json";   // last-resort synthetic fallback
const ROUTE_ROBUSTNESS_URL = "../route/app/gribs/robustness.json";
const ROUTE_SUMMARY_URL = "../route/app/gribs/summary.json";
const ROUTE_API_URL = "/api/route";
const ROUTE_API_TIMEOUT_MS = 45000;

async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status} from ${new URL(url, location.href).host}`);
  return r.json();
}

/* ---------------- wind & marine forecasts ---------------- */

// One call returns all six models; hourly keys come back suffixed with the model id.
async function fetchWind(point, days = 7) {
  const ids = MODELS.map(m => m.id).join(",");
  const url = OPEN_METEO_URL +
    `?latitude=${point.lat}&longitude=${point.lon}` +
    "&hourly=wind_speed_10m,wind_direction_10m,wind_gusts_10m" +
    `&models=${ids}&wind_speed_unit=ms&timeformat=unixtime&forecast_days=${days}`;
  const j = await fetchJson(url);
  const h = j.hourly;
  // unixtime is timezone-proof; Dates render in the browser's local time
  const times = h.time.map(t => new Date(t * 1000));
  const n = times.length;
  const num = a => (a || []).map(v => (v == null ? null : v));

  const perModel = {};
  for (const m of MODELS) {
    perModel[m.key] = {
      speed: num(h[`wind_speed_10m_${m.id}`]),
      dir: num(h[`wind_direction_10m_${m.id}`]),
      gust: num(h[`wind_gusts_10m_${m.id}`]),
    };
  }

  const blendSpeed = [], blendDir = [], blendGust = [], spread = [];
  for (let i = 0; i < n; i++) {
    blendSpeed.push(weighted(perModel, "speed", BLEND.speed, i));
    blendGust.push(weighted(perModel, "gust", BLEND.speed, i));
    blendDir.push(weightedDir(perModel, BLEND.direction, i));
    const vals = MODELS.map(m => perModel[m.key].speed[i]).filter(Number.isFinite);
    spread.push(vals.length ? Math.max(...vals) - Math.min(...vals) : null);
  }
  return { times, perModel, blendSpeed, blendDir, blendGust, spread };
}

// weighted mean over the models that reported a value, weights renormalized
function weighted(perModel, field, weights, i) {
  let sum = 0, wsum = 0;
  for (const m of MODELS) {
    const v = perModel[m.key][field][i];
    if (Number.isFinite(v)) { sum += weights[m.key] * v; wsum += weights[m.key]; }
  }
  return wsum > 0 ? sum / wsum : null;
}

// direction is circular: blend unit vectors, take the angle of the weighted sum
function weightedDir(perModel, weights, i) {
  let x = 0, y = 0, wsum = 0;
  for (const m of MODELS) {
    const d = perModel[m.key].dir[i];
    if (Number.isFinite(d)) {
      const r = d * Math.PI / 180;
      x += weights[m.key] * Math.sin(r);
      y += weights[m.key] * Math.cos(r);
      wsum += weights[m.key];
    }
  }
  if (wsum === 0 || (x === 0 && y === 0)) return null;
  return (Math.atan2(x, y) * 180 / Math.PI + 360) % 360;
}

async function fetchMarine(point, days = 5) {
  const url = MARINE_URL +
    `?latitude=${point.lat}&longitude=${point.lon}` +
    "&hourly=sea_level_height_msl,wave_height,ocean_current_velocity,ocean_current_direction" +
    `&timeformat=unixtime&forecast_days=${days}`;
  const j = await fetchJson(url);
  const h = j.hourly;
  return {
    times: h.time.map(t => new Date(t * 1000)),
    seaLevel: h.sea_level_height_msl || [],
    waveHeight: h.wave_height || [],
    currentKt: (h.ocean_current_velocity || []).map(v => (v == null ? null : kmhToKt(v))),
    currentDir: h.ocean_current_direction || [],
  };
}

/* ---------------- route data (route.html) ---------------- */

// POST the current vector to the live optimiser; throws on timeout or error
async function fetchLiveRoute(current) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ROUTE_API_TIMEOUT_MS);
  try {
    const res = await fetch(ROUTE_API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current }),
      signal: ctrl.signal,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `optimiser returned ${res.status}`);
    return data;
  } finally {
    clearTimeout(timer);
  }
}

// stored → today's CI-generated route first, synthetic sample only if that is missing
async function fetchStoredRoute() {
  for (const url of [ROUTE_TODAY_URL, ROUTE_SAMPLE_URL]) {
    try {
      const res = await fetch(url);
      if (res.ok) return await res.json();
    } catch { /* try the next one */ }
  }
  return null;
}

// LLM brief for the route page; null when unavailable
async function fetchRouteSummary() {
  try {
    const res = await fetch(ROUTE_SUMMARY_URL);
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

// robustness cross-evaluation KPIs; throws so the page can show the regen hint
async function fetchRobustness() {
  return fetchJson(ROUTE_ROBUSTNESS_URL);
}
