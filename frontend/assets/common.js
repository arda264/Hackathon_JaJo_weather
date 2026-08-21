/* DutchSail weather frontend — shared helpers, data access, and chart component. */
"use strict";

/* ---------------- theme ---------------- */

function effectiveTheme() {
  const t = document.documentElement.dataset.theme;
  if (t === "light" || t === "dark") return t;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

const themeListeners = [];
function onThemeChange(fn) { themeListeners.push(fn); }
function notifyTheme() { const t = effectiveTheme(); themeListeners.forEach(fn => fn(t)); }

function initChrome() {
  const btn = document.querySelector(".theme-toggle");
  if (btn) {
    const labels = { auto: "Theme: auto", light: "Theme: light", dark: "Theme: dark" };
    const urlTheme = new URLSearchParams(location.search).get("theme");
    let mode = (urlTheme === "light" || urlTheme === "dark") ? urlTheme
      : localStorage.getItem("ds-theme") || "auto";
    const apply = () => {
      if (mode === "auto") delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = mode;
      btn.textContent = labels[mode];
      notifyTheme();
    };
    btn.addEventListener("click", () => {
      mode = mode === "auto" ? "light" : mode === "light" ? "dark" : "auto";
      if (mode === "auto") localStorage.removeItem("ds-theme");
      else localStorage.setItem("ds-theme", mode);
      apply();
    });
    apply();
  }
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", notifyTheme);

  // static PNGs exist in light and dark renders — swap src with the theme
  const swap = () => {
    const t = effectiveTheme();
    document.querySelectorAll("img[data-light]").forEach(img => {
      img.src = t === "dark" ? img.dataset.dark : img.dataset.light;
    });
  };
  onThemeChange(swap);
  swap();
}

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

function currentPoint() {
  const saved = localStorage.getItem("ds-point");
  return POINTS.find(p => `${p.lat},${p.lon}` === saved) || POINTS[0];
}

function initPointSelect(sel, onChange) {
  POINTS.forEach(p => {
    const o = document.createElement("option");
    o.value = `${p.lat},${p.lon}`;
    o.textContent = p.name;
    sel.append(o);
  });
  sel.value = `${currentPoint().lat},${currentPoint().lon}`;
  sel.addEventListener("change", () => {
    localStorage.setItem("ds-point", sel.value);
    onChange(currentPoint());
  });
}

/* ---------------- units & formatting ---------------- */

const msToKt = v => v * 1.9438445;
const kmhToKt = v => v / 1.852;

function beaufort(ms) {
  const t = [0.5, 1.5, 3.3, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5, 32.7];
  let b = 0;
  while (b < t.length && ms >= t[b]) b++;
  return b;
}

function compass16(deg) {
  const names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  return names[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16];
}

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const pad2 = n => String(n).padStart(2, "0");
const fmtDay = d => `${DAYS[d.getDay()]} ${d.getDate()}`;
const fmtHour = d => `${pad2(d.getHours())}:00`;
const fmtFull = d => `${fmtDay(d)} · ${fmtHour(d)}`;

/* ---------------- data fetch ---------------- */

async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status} from ${new URL(url).host}`);
  return r.json();
}

// One call returns all six models; hourly keys come back suffixed with the model id.
async function fetchWind(point, days = 7) {
  const ids = MODELS.map(m => m.id).join(",");
  const url = "https://api.open-meteo.com/v1/forecast" +
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
  const url = "https://marine-api.open-meteo.com/v1/marine" +
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

function nowIndexOf(times) {
  const now = Date.now();
  let idx = 0;
  for (let i = 0; i < times.length; i++) if (times[i].getTime() <= now) idx = i;
  return idx;
}

/* ---------------- chart component ---------------- */

const cssColor = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

function niceTicks(min, max, count = 5) {
  if (min === max) { min -= 1; max += 1; }
  const span = max - min;
  const step0 = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= count) || 10 * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step; // top tick must cover the max or lines clip past the plot
  const ticks = [];
  for (let v = lo; v <= hi + step * 0.001; v += step) ticks.push(+v.toFixed(6));
  return ticks;
}

/**
 * SVG line chart with crosshair + tooltip, legend toggles and a table view.
 * cfg: { times, series:[{id,name,color,values,width,endLabel}], unit, decimals,
 *        yMin, nowIndex, tableTimeLabel }
 */
function lineChart(mount, cfg) {
  const W = 920, H = 300, L = 48, R = 16, T = 14, B = 26;
  const PW = W - L - R, PH = H - T - B;
  const n = cfg.times.length;
  const dec = cfg.decimals ?? 1;
  const visible = new Set(cfg.series.map(s => s.id));

  mount.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "chart-svg-wrap";
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", cfg.ariaLabel || "line chart");
  const tooltip = document.createElement("div");
  tooltip.className = "chart-tooltip";
  wrap.append(svg, tooltip);
  mount.append(wrap);

  // legend (always present for >= 2 series) + table toggle in one row
  const controls = document.createElement("div");
  controls.style.display = "flex";
  controls.style.alignItems = "center";
  controls.style.flexWrap = "wrap";
  controls.style.gap = "8px";
  const legend = document.createElement("ul");
  legend.className = "chart-legend";
  if (cfg.series.length > 1) {
    for (const s of cfg.series) {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.setAttribute("aria-pressed", "true");
      const key = document.createElement("span");
      key.className = "key";
      key.style.borderTopColor = `var(${s.color})`;
      b.append(key, document.createTextNode(s.name));
      b.addEventListener("click", () => {
        if (visible.has(s.id)) { if (visible.size === 1) return; visible.delete(s.id); }
        else visible.add(s.id);
        b.setAttribute("aria-pressed", String(visible.has(s.id)));
        draw();
      });
      li.append(b);
      legend.append(li);
    }
  }
  const spacer = document.createElement("div");
  spacer.style.flex = "1";
  const tbtn = document.createElement("button");
  tbtn.className = "table-toggle";
  tbtn.textContent = "Table";
  tbtn.setAttribute("aria-pressed", "false");
  controls.append(legend, spacer, tbtn);
  mount.append(controls);

  const tableWrap = document.createElement("div");
  tableWrap.className = "data-table-wrap";
  tableWrap.hidden = true;
  tableWrap.append(makeTable(cfg.times, [
    ...cfg.series.map(s => ({ name: `${s.name} (${cfg.unit})`, values: s.values, fmt: v => v.toFixed(dec) })),
  ], cfg.tableTimeLabel || "Time"));
  mount.append(tableWrap);
  tbtn.addEventListener("click", () => {
    tableWrap.hidden = !tableWrap.hidden;
    tbtn.setAttribute("aria-pressed", String(!tableWrap.hidden));
  });

  const x = i => L + (n <= 1 ? 0 : i * PW / (n - 1));

  function draw() {
    const shown = cfg.series.filter(s => visible.has(s.id));
    let mn = cfg.yMin ?? Infinity, mx = -Infinity;
    for (const s of shown) for (const v of s.values) if (Number.isFinite(v)) { mn = Math.min(mn, v); mx = Math.max(mx, v); }
    if (!Number.isFinite(mn) || !Number.isFinite(mx)) { mn = 0; mx = 1; }
    const ticks = niceTicks(mn, mx, 5);
    const lo = ticks[0], hi = ticks[ticks.length - 1];
    const y = v => T + PH - (v - lo) / (hi - lo) * PH;

    const el = [];
    // hairline gridlines + y ticks
    for (const t of ticks) {
      el.push(`<line x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}" stroke="var(--grid)" stroke-width="1"/>`);
      el.push(`<text x="${L - 7}" y="${y(t) + 3.5}" text-anchor="end" font-size="11" fill="var(--muted)" style="font-variant-numeric:tabular-nums">${+t.toFixed(3)}</text>`);
    }
    // baseline
    const baseV = lo <= 0 && hi >= 0 ? 0 : lo;
    el.push(`<line x1="${L}" x2="${W - R}" y1="${y(baseV)}" y2="${y(baseV)}" stroke="var(--baseline)" stroke-width="1"/>`);
    // x ticks at local midnights
    for (let i = 0; i < n; i++) {
      if (cfg.times[i].getHours() === 0 || (i === 0 && n < 30)) {
        el.push(`<line x1="${x(i)}" x2="${x(i)}" y1="${T + PH}" y2="${T + PH + 4}" stroke="var(--baseline)" stroke-width="1"/>`);
        el.push(`<text x="${x(i)}" y="${H - 8}" text-anchor="middle" font-size="11" fill="var(--muted)">${fmtDay(cfg.times[i])}</text>`);
      }
    }
    // "now" marker
    if (cfg.nowIndex != null && cfg.nowIndex > 0) {
      el.push(`<line x1="${x(cfg.nowIndex)}" x2="${x(cfg.nowIndex)}" y1="${T}" y2="${T + PH}" stroke="var(--baseline)" stroke-width="1"/>`);
      el.push(`<text x="${x(cfg.nowIndex) + 4}" y="${T + 10}" font-size="10" fill="var(--muted)">now</text>`);
    }
    // series
    for (const s of shown) {
      const segs = [];
      let seg = [];
      for (let i = 0; i < n; i++) {
        const v = s.values[i];
        if (Number.isFinite(v)) seg.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`);
        else if (seg.length) { segs.push(seg); seg = []; }
      }
      if (seg.length) segs.push(seg);
      if (shown.length === 1) {
        for (const g of segs) {
          if (g.length < 2) continue;
          const first = g[0].split(","), last = g[g.length - 1].split(",");
          el.push(`<path d="M${first[0]},${y(baseV)} L${g.join(" L")} L${last[0]},${y(baseV)} Z" fill="var(${s.color})" opacity="0.1"/>`);
        }
      }
      for (const g of segs) {
        if (g.length === 1) {
          const [px, py] = g[0].split(",");
          el.push(`<circle cx="${px}" cy="${py}" r="3" fill="var(${s.color})"/>`);
        } else {
          el.push(`<path d="M${g.join(" L")}" fill="none" stroke="var(${s.color})" stroke-width="${s.width || 2}" stroke-linejoin="round" stroke-linecap="round"/>`);
        }
      }
      // end marker with a 2px surface ring
      let last = -1;
      for (let i = n - 1; i >= 0; i--) if (Number.isFinite(s.values[i])) { last = i; break; }
      if (last >= 0) {
        el.push(`<circle cx="${x(last)}" cy="${y(s.values[last])}" r="4.5" fill="var(${s.color})" stroke="var(--surface)" stroke-width="2"/>`);
        if (s.endLabel) {
          el.push(`<text x="${x(last) - 8}" y="${y(s.values[last]) - 9}" text-anchor="end" font-size="11.5" font-weight="650" fill="var(--ink)" style="font-variant-numeric:tabular-nums">${s.values[last].toFixed(dec)} ${cfg.unit}</text>`);
        }
      }
    }
    // point annotations (e.g. tide highs/lows) — selective direct labels
    for (const a of cfg.annotations || []) {
      const s = shown[0];
      if (!s || !Number.isFinite(s.values[a.i])) continue;
      const ax = x(a.i), ay = y(s.values[a.i]);
      el.push(`<circle cx="${ax}" cy="${ay}" r="4.5" fill="var(${s.color})" stroke="var(--surface)" stroke-width="2"/>`);
      const above = a.type !== "low";
      el.push(`<text x="${ax}" y="${above ? ay - 10 : ay + 18}" text-anchor="middle" font-size="11" font-weight="650" fill="var(--ink)" style="font-variant-numeric:tabular-nums">${a.text}</text>`);
    }
    // crosshair placeholder (managed on pointermove)
    el.push(`<line class="xhair" x1="0" x2="0" y1="${T}" y2="${T + PH}" stroke="var(--baseline)" stroke-width="1" visibility="hidden"/>`);
    el.push(`<rect class="hover" x="${L}" y="${T}" width="${PW}" height="${PH}" fill="transparent" tabindex="0" aria-label="chart values; use arrow keys"/>`);
    svg.innerHTML = el.join("");
    wireHover(shown);
  }

  function wireHover(shown) {
    const hover = svg.querySelector("rect.hover");
    const xhair = svg.querySelector("line.xhair");
    let idx = null;

    const show = i => {
      idx = Math.max(0, Math.min(n - 1, i));
      const rect = svg.getBoundingClientRect();
      const scale = rect.width / W;
      xhair.setAttribute("x1", x(idx));
      xhair.setAttribute("x2", x(idx));
      xhair.setAttribute("visibility", "visible");
      tooltip.innerHTML = "";
      const tEl = document.createElement("div");
      tEl.className = "tt-time";
      tEl.textContent = fmtFull(cfg.times[idx]);
      tooltip.append(tEl);
      const rows = shown
        .map(s => ({ s, v: s.values[idx] }))
        .filter(r => Number.isFinite(r.v))
        .sort((a, b) => b.v - a.v);
      for (const r of rows) {
        const row = document.createElement("div");
        row.className = "tt-row";
        const key = document.createElement("span");
        key.className = "tt-key";
        key.style.borderTopColor = `var(${r.s.color})`;
        const val = document.createElement("span");
        val.className = "tt-val";
        val.textContent = `${r.v.toFixed(dec)} ${cfg.unit}`;
        const name = document.createElement("span");
        name.className = "tt-name";
        name.textContent = r.s.name;
        row.append(key, val, name);
        tooltip.append(row);
      }
      tooltip.style.display = "block";
      const px = x(idx) * scale;
      const flip = px > rect.width * 0.62;
      tooltip.style.left = flip ? "" : `${px + 14}px`;
      tooltip.style.right = flip ? `${rect.width - px + 14}px` : "";
      tooltip.style.top = `${T * scale + 8}px`;
    };
    const hide = () => { idx = null; xhair.setAttribute("visibility", "hidden"); tooltip.style.display = "none"; };

    hover.addEventListener("pointermove", e => {
      const rect = svg.getBoundingClientRect();
      const scale = rect.width / W;
      const gx = (e.clientX - rect.left) / scale;
      show(Math.round((gx - L) / PW * (n - 1)));
    });
    hover.addEventListener("pointerleave", hide);
    hover.addEventListener("focus", () => show(cfg.nowIndex ?? 0));
    hover.addEventListener("blur", hide);
    hover.addEventListener("keydown", e => {
      if (e.key === "ArrowRight") { show((idx ?? 0) + 1); e.preventDefault(); }
      if (e.key === "ArrowLeft") { show((idx ?? 0) - 1); e.preventDefault(); }
      if (e.key === "Escape") hide();
    });
  }

  draw();
}

/* arrows along the time axis showing where the wind/current blows toward */
function directionStrip(mount, times, dirs, opts = {}) {
  const W = 920, H = 44, L = 48, R = 16;
  const n = times.length, step = opts.step || 3;
  const PW = W - L - R;
  const x = i => L + (n <= 1 ? 0 : i * PW / (n - 1));
  const el = [];
  el.push(`<text x="${L - 7}" y="26" text-anchor="end" font-size="11" fill="var(--muted)">${opts.label || "dir"}</text>`);
  for (let i = 0; i < n; i += step) {
    const d = dirs[i];
    if (!Number.isFinite(d)) continue;
    // wind is meteorological (FROM), currents oceanographic (TOWARD); arrows always point where the flow goes
    const rot = opts.toward ? d : (d + 180) % 360;
    el.push(`<g transform="translate(${x(i)},22) rotate(${rot})">` +
      `<line x1="0" y1="7" x2="0" y2="-7" stroke="var(--ink-2)" stroke-width="1.8" stroke-linecap="round"/>` +
      `<path d="M-3.5,-2.5 L0,-8 L3.5,-2.5" fill="none" stroke="var(--ink-2)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>` +
      `<title>${fmtFull(times[i])} — ${compass16(d)} ${Math.round(d)}°</title></g>`);
  }
  mount.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${opts.label || "direction"} arrows">${el.join("")}</svg>`;
}

function makeTable(times, columns, timeLabel = "Time") {
  const table = document.createElement("table");
  table.className = "data-table";
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  const th0 = document.createElement("th");
  th0.textContent = timeLabel;
  hr.append(th0);
  for (const c of columns) {
    const th = document.createElement("th");
    th.textContent = c.name;
    hr.append(th);
  }
  thead.append(hr);
  const tbody = document.createElement("tbody");
  for (let i = 0; i < times.length; i++) {
    const tr = document.createElement("tr");
    const td0 = document.createElement("td");
    td0.textContent = fmtFull(times[i]);
    tr.append(td0);
    for (const c of columns) {
      const td = document.createElement("td");
      const v = c.values[i];
      td.textContent = Number.isFinite(v) ? c.fmt(v) : "–";
      tr.append(td);
    }
    tbody.append(tr);
  }
  table.append(thead, tbody);
  return table;
}

/* local extremes (tide highs/lows) */
function findExtremes(values) {
  const out = [];
  for (let i = 1; i < values.length - 1; i++) {
    const a = values[i - 1], b = values[i], c = values[i + 1];
    if (!Number.isFinite(a) || !Number.isFinite(b) || !Number.isFinite(c)) continue;
    if (b >= a && b > c) out.push({ i, type: "high" });
    else if (b <= a && b < c) out.push({ i, type: "low" });
  }
  return out;
}

function statusMsg(mount, text, retry) {
  mount.innerHTML = "";
  const div = document.createElement("div");
  div.className = "status-msg error";
  div.textContent = text;
  if (retry) {
    const b = document.createElement("button");
    b.textContent = "Retry";
    b.addEventListener("click", retry);
    div.append(b);
  }
  mount.append(div);
}

document.addEventListener("DOMContentLoaded", initChrome);
