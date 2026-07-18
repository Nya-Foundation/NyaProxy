/* ===========================================================================
 * NyaProxy dashboard — "Coin Cat" UI.
 *
 * Dependency-free client. Polls the dashboard JSON API every 15 s and
 * re-renders each band from cached state; expansion, filters, sort, and
 * confirm states key on state (not DOM), so every render is idempotent.
 *
 * Two data sources with different authority, kept distinct on screen:
 *   /api/metrics  — counters since the last reset. Authoritative totals.
 *   /api/history  — a bounded ring buffer of recent responses. Everything
 *                   time-based (trends, percentiles, per-key error rates)
 *                   is derived from this sample and is always labelled as
 *                   "recent", never presented as an all-time figure.
 * ========================================================================= */
"use strict";

/* --- constants ------------------------------------------------------------ */

const API = new URL("api", new URL(".", window.location.href)).href;
const BASE_REFRESH_MS = 15000;
const MAX_REFRESH_MS = 60000;
const HISTORY_LIMIT = 200;
const STATUS_CLASSES = ["2xx", "4xx", "5xx", "other"];

/* Buckets used for every time series. One shared grid keeps the tile
   sparklines and the per-API trends on the same time axis. */
const SERIES_BUCKETS = 32;

const COIN_GLYPH =
  '<svg class="coin-glyph" viewBox="0 0 40 40" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">' +
  '<circle cx="20" cy="20" r="15" />' +
  '<line x1="6" y1="24" x2="34" y2="24" /></svg>';

const CHEVRON_SVG =
  '<svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">' +
  '<path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" /></svg>';

/* --- state ---------------------------------------------------------------- */

const state = {
  metrics: null,
  history: null,
  queues: null,
  derived: null, // computed from history on every successful fetch
  apiFilter: "",
  historyFilter: "",
  statusChip: "all",
  historyApi: null, // cross-filter: show only this API in the traffic log
  historyKey: null, // cross-filter: show only this credential
  sort: { key: "requests", dir: "desc" },
  openApi: null,
  idleOpen: false,
  confirm: null, // key of the armed destructive control, or null
  sections: {
    metrics: { lastSuccess: 0, failed: false, attempted: false },
    history: { lastSuccess: 0, failed: false, attempted: false },
    queues: { lastSuccess: 0, failed: false, attempted: false },
  },
  refreshMs: BASE_REFRESH_MS,
  inFlight: false,
  failStreak: 0,
  wasStale: false,
  prevPulse: {},
  restoredFromHash: false,
};

let refreshTimer = null;
const confirmReverters = {}; // key -> () => void  (static two-step buttons)

const $ = (id) => document.getElementById(id);

function setCount(id, value, title) {
  const el = $(id);
  if (!el) return;
  el.textContent = fmt.compact(value);
  el.hidden = false;
  if (title) el.title = title;
}

/* --- formatting ----------------------------------------------------------- */

const fmt = {
  int(n) {
    return (n || 0).toLocaleString("en-US");
  },
  compact(n) {
    n = n || 0;
    const trim = (v, suffix) => v.toFixed(1).replace(/\.0$/, "") + suffix;
    if (n >= 1e9) return trim(n / 1e9, "B");
    if (n >= 1e6) return trim(n / 1e6, "M");
    if (n >= 1e4) return trim(n / 1e3, "K");
    return n.toLocaleString("en-US");
  },
  latency(ms) {
    if (!ms) return "—";
    return ms >= 1000 ? (ms / 1000).toFixed(1) + "s" : Math.round(ms) + "ms";
  },
  rate(n) {
    if (n >= 100) return Math.round(n).toLocaleString("en-US");
    if (n >= 10) return n.toFixed(0);
    return n.toFixed(1).replace(/\.0$/, "");
  },
  duration(seconds) {
    const s = Math.floor(seconds || 0);
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s % 60}s`;
    return `${s}s`;
  },
  ago(epochSeconds) {
    if (!epochSeconds) return "—";
    const delta = Math.max(0, Date.now() / 1000 - epochSeconds);
    if (delta < 60) return `${Math.floor(delta)}s ago`;
    if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
    if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
    return `${Math.floor(delta / 86400)}d ago`;
  },
  time(epochSeconds) {
    return new Date(epochSeconds * 1000).toLocaleTimeString("en-US", {
      hour12: false,
    });
  },
  clock(epochSeconds) {
    return new Date(epochSeconds * 1000).toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
    });
  },
};

function statusClass(code) {
  const c = Number(code);
  if (c >= 200 && c < 300) return "2xx";
  if (c >= 400 && c < 500) return "4xx";
  if (c >= 500) return "5xx";
  return "other";
}

/* A response counts as an error on the same terms the server uses:
   4xx/5xx, plus status 0 — the sentinel for a transport failure. */
function isError(code) {
  const c = Number(code);
  return c >= 400 || c === 0;
}

const BADGE_BY_CLASS = {
  "2xx": "badge-ok",
  "4xx": "badge-warn",
  "5xx": "badge-err",
  other: "badge-neutral",
};

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );
}

function slug(name) {
  return encodeURIComponent(name).replace(/[^A-Za-z0-9_-]/g, "_");
}

function attrSel(value) {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function focusKey(key) {
  const el = document.querySelector(`[data-focus-key="${attrSel(key)}"]`);
  if (el) el.focus();
}

/* Re-render a container while keeping keyboard focus on the "same" control. */
function withFocusRestore(container, render) {
  const active = document.activeElement;
  const key =
    active && container.contains(active) ? active.dataset.focusKey : null;
  render();
  if (key) {
    const el = container.querySelector(`[data-focus-key="${attrSel(key)}"]`);
    if (el) el.focus();
  }
}

/* --- derived analytics ------------------------------------------------------
 * The history endpoint hands us up to 2000 timestamped responses, each with
 * a status code, a latency, and the credential that served it. Everything
 * below is folded out of that one pass so the UI can show trend, spread, and
 * credential health without any extra requests.
 * ------------------------------------------------------------------------- */

function percentile(sortedValues, p) {
  if (!sortedValues.length) return 0;
  const rank = Math.ceil((p / 100) * sortedValues.length) - 1;
  return sortedValues[Math.min(sortedValues.length - 1, Math.max(0, rank))];
}

function newBucket() {
  return { total: 0, errors: 0, latencies: [] };
}

function deriveAnalytics(history, metrics) {
  const responses = (history || []).filter(
    (e) => e && e.type === "response" && e.timestamp
  );
  if (!responses.length) return null;

  const now = Date.now() / 1000;
  const first = responses.reduce(
    (min, e) => Math.min(min, e.timestamp),
    Infinity
  );
  // The window runs from the oldest sampled response to now, so an idle
  // gateway visibly trails off instead of freezing at its last request.
  const spanSec = Math.max(1, now - first);
  const bucketSec = Math.max(1, spanSec / SERIES_BUCKETS);

  const buckets = Array.from({ length: SERIES_BUCKETS }, newBucket);
  const perApi = new Map();
  const perKey = new Map();
  const latencies = [];

  for (const e of responses) {
    const idx = Math.min(
      SERIES_BUCKETS - 1,
      Math.max(0, Math.floor((e.timestamp - first) / bucketSec))
    );
    const err = isError(e.status_code);
    const ms = Number(e.elapsed_ms) || 0;

    const b = buckets[idx];
    b.total += 1;
    if (err) b.errors += 1;
    if (ms) b.latencies.push(ms);
    if (ms) latencies.push(ms);

    if (e.api_name != null) {
      let a = perApi.get(e.api_name);
      if (!a) {
        a = {
          buckets: Array.from({ length: SERIES_BUCKETS }, () => 0),
          total: 0,
          errors: 0,
          latencies: [],
        };
        perApi.set(e.api_name, a);
      }
      a.buckets[idx] += 1;
      a.total += 1;
      if (err) a.errors += 1;
      if (ms) a.latencies.push(ms);
    }

    if (e.key_id != null) {
      let k = perKey.get(e.key_id);
      if (!k) {
        k = { total: 0, errors: 0, lastSeen: 0, apis: new Set(), latencies: [] };
        perKey.set(e.key_id, k);
      }
      k.total += 1;
      if (err) k.errors += 1;
      if (ms) k.latencies.push(ms);
      k.lastSeen = Math.max(k.lastSeen, e.timestamp);
      if (e.api_name != null) k.apis.add(e.api_name);
    }
  }

  const sortedLatencies = latencies.slice().sort((a, b) => a - b);

  // Latency distribution, scaled to p99 so a handful of slow outliers cannot
  // flatten the shape of the bulk. Anything past p99 lands in the last bin.
  const HIST_BINS = 28;
  const histMax = percentile(sortedLatencies, 99) || 1;
  const binMs = histMax / HIST_BINS;
  const hist = new Array(HIST_BINS).fill(0);
  for (const ms of sortedLatencies) {
    hist[Math.min(HIST_BINS - 1, Math.floor(ms / binMs))] += 1;
  }

  // Throughput reads off the tail of the sample. If we have not observed a
  // full minute yet, project the shorter window and say so in the label.
  const rateWindow = Math.min(60, spanSec);
  const cutoff = now - rateWindow;
  const recentCount = responses.filter((e) => e.timestamp >= cutoff).length;

  const apis = {};
  for (const [name, a] of perApi) {
    const sorted = a.latencies.slice().sort((x, y) => x - y);
    apis[name] = {
      series: a.buckets,
      total: a.total,
      errors: a.errors,
      errorRate: a.total ? (a.errors / a.total) * 100 : 0,
      p95: percentile(sorted, 95),
    };
  }

  // All-time per-key totals come from the metrics counters; the history
  // sample only contributes the failure and recency signal.
  const keyTotals = new Map();
  const keyApis = new Map();
  for (const [apiName, data] of Object.entries(
    (metrics && metrics.apis) || {}
  )) {
    for (const [keyId, total] of Object.entries(data.key_usage || {})) {
      keyTotals.set(keyId, (keyTotals.get(keyId) || 0) + total);
      if (!keyApis.has(keyId)) keyApis.set(keyId, new Set());
      keyApis.get(keyId).add(apiName);
    }
  }

  const keyIds = new Set([...keyTotals.keys(), ...perKey.keys()]);
  const keys = [...keyIds]
    .map((id) => {
      const recent = perKey.get(id) || {
        total: 0,
        errors: 0,
        lastSeen: 0,
        apis: new Set(),
      };
      const apiSet = keyApis.get(id) || recent.apis;
      return {
        id,
        total: keyTotals.get(id) || recent.total,
        recentTotal: recent.total,
        recentErrors: recent.errors,
        errorRate: recent.total ? (recent.errors / recent.total) * 100 : 0,
        lastSeen: recent.lastSeen,
        apis: [...apiSet].sort(),
      };
    })
    .sort((a, b) => b.total - a.total || a.id.localeCompare(b.id));

  const keyTotalSum = keys.reduce((sum, k) => sum + k.total, 0);

  return {
    first,
    spanSec,
    bucketSec,
    sampleSize: responses.length,
    buckets,
    traffic: buckets.map((b) => b.total / (bucketSec / 60)),
    errorRates: buckets.map((b) => (b.total ? (b.errors / b.total) * 100 : 0)),
    latencyTrend: buckets.map((b) =>
      percentile(b.latencies.slice().sort((a, c) => a - c), 95)
    ),
    throughputPerMin: (recentCount / rateWindow) * 60,
    rateWindow,
    p50: percentile(sortedLatencies, 50),
    p95: percentile(sortedLatencies, 95),
    p99: percentile(sortedLatencies, 99),
    hist,
    binMs,
    latencySamples: sortedLatencies.length,
    apis,
    keys,
    keyTotalSum,
  };
}

/* --- microcharts ------------------------------------------------------------
 * Every chart sits on the horizon rule — the same 1px baseline the section
 * heads use — so the tiles, the ledger, and the latency axis read as one
 * family rather than three chart styles.
 * ------------------------------------------------------------------------- */

function bucketLabel(d, i) {
  const start = d.first + i * d.bucketSec;
  return fmt.clock(start);
}

function sparkBars(values, opts) {
  const { tone = "accent", label = "", format = fmt.rate, derived } = opts || {};
  if (!values || !values.length) return "";
  const max = Math.max(...values);
  const n = values.length;
  const gap = 0.18; // share of each slot left as breathing room
  const slot = 100 / n;
  const w = slot * (1 - gap);

  const bars = values
    .map((v, i) => {
      const h = max > 0 ? (v / max) * 100 : 0;
      const x = i * slot + (slot * gap) / 2;
      const title = derived
        ? `<title>${escapeHtml(bucketLabel(derived, i))} · ${escapeHtml(
            format(v)
          )}${label ? " " + escapeHtml(label) : ""}</title>`
        : "";
      // Zero buckets still get a hairline so idle time reads as observed,
      // not as missing data.
      const height = Math.max(h, v > 0 ? 2 : 0.8);
      return `<rect class="spark-bar${v > 0 ? "" : " is-zero"}" x="${x.toFixed(
        2
      )}" y="${(100 - height).toFixed(2)}" width="${w.toFixed(
        2
      )}" height="${height.toFixed(2)}">${title}</rect>`;
    })
    .join("");

  return `<svg class="spark spark-${tone}" viewBox="0 0 100 100" preserveAspectRatio="none" role="presentation" focusable="false">
    ${bars}<line class="spark-horizon" x1="0" y1="99.5" x2="100" y2="99.5" />
  </svg>`;
}

/* The latency chart: a distribution sitting on the horizon rule, with the
   three percentiles pinned beneath the same rule. One shared 0→p99 scale, so
   the pins read as positions in the distribution rather than loose numbers —
   which is what tells you whether latency is one hump or two. */
function latencyChartHtml(d) {
  if (!d || !d.latencySamples) {
    return `<div class="axis-empty">No latency samples yet.</div>`;
  }
  const max = Math.max(d.p99, 1);
  const peak = Math.max(...d.hist, 1);
  const n = d.hist.length;
  const slot = 100 / n;
  const gap = 0.16;
  const w = slot * (1 - gap);

  const bars = d.hist
    .map((count, i) => {
      const h = Math.max((count / peak) * 100, count > 0 ? 2 : 0);
      const x = i * slot + (slot * gap) / 2;
      const lo = fmt.latency(i * d.binMs);
      const hi = fmt.latency((i + 1) * d.binMs);
      return `<rect class="hist-bar" x="${x.toFixed(2)}" y="${(
        100 - h
      ).toFixed(2)}" width="${w.toFixed(2)}" height="${h.toFixed(2)}">
        <title>${escapeHtml(lo)}–${escapeHtml(hi)} · ${fmt.int(
        count
      )} responses</title></rect>`;
    })
    .join("");

  const marks = [
    { key: "p50", value: d.p50, label: "median" },
    { key: "p95", value: d.p95, label: "95th percentile" },
    { key: "p99", value: d.p99, label: "99th percentile" },
  ];
  const pins = marks
    .map((m) => {
      const pct = Math.min(100, (m.value / max) * 100);
      return `<span class="axis-pin axis-${m.key}" style="left:${pct.toFixed(
        1
      )}%" title="${escapeHtml(m.label)} — ${escapeHtml(fmt.latency(m.value))}">
        <i aria-hidden="true"></i>
        <span class="pin-value">${escapeHtml(fmt.latency(m.value))}</span>
        <span class="pin-key">${m.key}</span>
      </span>`;
    })
    .join("");

  return `<div class="lat-chart" role="img" aria-label="Latency distribution of ${fmt.int(
    d.latencySamples
  )} recent responses. Median ${fmt.latency(d.p50)}, 95th percentile ${fmt.latency(
    d.p95
  )}, 99th percentile ${fmt.latency(d.p99)}.">
    <svg class="lat-hist" viewBox="0 0 100 100" preserveAspectRatio="none" focusable="false">${bars}</svg>
    <div class="lat-rule" aria-hidden="true"></div>
    <div class="lat-pins">${pins}</div>
    <div class="axis-scale" aria-hidden="true"><span>0</span><span>${escapeHtml(
      fmt.latency(max)
    )}+</span></div>
  </div>`;
}

/* --- API client ----------------------------------------------------------- */

async function getJSON(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

async function postJSON(path) {
  const res = await fetch(`${API}${path}`, { method: "POST" });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

/* --- live regions --------------------------------------------------------- */

let toastTimer = null;
function toast(message, kind = "ok") {
  const node = $("toast");
  $("toast-msg").textContent = message;
  node.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.className = "toast"), 3200);
}

let announceTimer = null;
function announce(message) {
  clearTimeout(announceTimer);
  announceTimer = setTimeout(() => {
    $("announcer").textContent = message;
  }, 500);
}

/* --- URL hash (deep links: #api=<name>&status=<class>&key=<id>) ------------ */

function readHash() {
  const out = { api: null, status: "all", key: null };
  for (const part of window.location.hash.replace(/^#/, "").split("&")) {
    const eq = part.indexOf("=");
    if (eq < 0) continue;
    const k = part.slice(0, eq);
    const v = part.slice(eq + 1);
    if ((k === "api" || k === "key") && v) {
      try {
        out[k] = decodeURIComponent(v);
      } catch {}
    } else if (k === "status" && STATUS_CLASSES.includes(v)) {
      out.status = v;
    }
  }
  return out;
}

function writeHash(push = false) {
  const parts = [];
  if (state.openApi) parts.push("api=" + encodeURIComponent(state.openApi));
  if (state.statusChip !== "all") parts.push("status=" + state.statusChip);
  if (state.historyKey) parts.push("key=" + encodeURIComponent(state.historyKey));
  const hash = parts.length ? "#" + parts.join("&") : "";
  if (hash === window.location.hash) return;
  if (push && hash) {
    window.location.hash = hash; // history entry → browser Back closes it
  } else {
    history.replaceState(
      null,
      "",
      window.location.pathname + window.location.search + hash
    );
  }
}

function onHashChange() {
  // Section navigation shares the URL fragment with dashboard deep links.
  // Scrolling between sections must not clear active API/status filters.
  if (
    ["#overview", "#apis", "#activity", "#credentials"].includes(
      window.location.hash
    )
  )
    return;
  const h = readHash();
  let apisDirty = false;
  let historyDirty = false;
  if (h.api !== state.openApi) {
    state.openApi = h.api;
    apisDirty = true;
  }
  if (h.status !== state.statusChip) {
    state.statusChip = h.status;
    historyDirty = true;
  }
  if (h.key !== state.historyKey) {
    state.historyKey = h.key;
    historyDirty = true;
  }
  if (apisDirty) renderApis();
  if (historyDirty) {
    renderHistory();
    renderKeys();
  }
}

/* --- Band A: intro meta ---------------------------------------------------- */

function renderIntroMeta() {
  const g = state.metrics && state.metrics.global;
  $("meta-uptime").textContent = g ? fmt.duration(g.uptime_seconds) : "—";

  const d = state.derived;
  const el = $("meta-window");
  if (!d) {
    el.textContent = "—";
    el.removeAttribute("title");
    return;
  }
  el.textContent = `${fmt.duration(d.spanSec)} · ${fmt.compact(
    d.sampleSize
  )} responses`;
  el.title = `Trends and percentiles are derived from the ${fmt.int(
    d.sampleSize
  )} most recent responses, covering ${fmt.duration(d.spanSec)}.`;
}

/* --- Band B: pulse tiles --------------------------------------------------- */

function setPulseValue(id, text, title) {
  const el = $(id);
  el.classList.remove("skel", "skel-value");
  if (title != null) el.title = title;
  else el.removeAttribute("title");
  if (el.textContent === text) return;
  el.textContent = text;
  const prev = state.prevPulse[id];
  state.prevPulse[id] = text;
  if (prev === undefined) return; // first paint — no pulse
  const tile = el.closest(".tile");
  if (tile) {
    tile.classList.remove("pulse");
    void tile.offsetWidth; // restart the animation
    tile.classList.add("pulse");
  }
}

function renderPulse() {
  const g = state.metrics && state.metrics.global;
  const d = state.derived;

  if (!g) {
    if (!state.sections.metrics.attempted) return;
    for (const id of [
      "tile-throughput-value",
      "tile-error-value",
      "tile-latency-value",
      "tile-pressure-value",
    ])
      setPulseValue(id, "—");
    return;
  }

  /* Throughput — a rate, so it only exists if we have a sample to measure. */
  if (d) {
    setPulseValue("tile-throughput-value", fmt.rate(d.throughputPerMin));
    $("tile-throughput-spark").innerHTML = sparkBars(d.traffic, {
      tone: "accent",
      label: "req/min",
      derived: d,
    });
    $("tile-throughput-sub").textContent =
      d.rateWindow >= 60
        ? `measured over the last 60s`
        : `measured over the last ${Math.round(d.rateWindow)}s`;
  } else {
    setPulseValue("tile-throughput-value", "0");
    $("tile-throughput-spark").innerHTML = "";
    $("tile-throughput-sub").textContent = "no responses sampled yet";
  }

  /* Error rate — the headline is the authoritative all-time counter; the
     sparkline underneath is the recent trend from the history sample. */
  const rate = g.total_requests ? (g.total_errors / g.total_requests) * 100 : 0;
  setPulseValue("tile-error-value", `${rate.toFixed(2)}%`);
  const dot = $("tile-error-dot");
  dot.hidden = false;
  dot.className = "dot " + (rate > 5 ? "dot-err" : "dot-ok");
  $("tile-error-spark").innerHTML = d
    ? sparkBars(d.errorRates, {
        tone: "err",
        label: "errors",
        format: (v) => v.toFixed(1) + "%",
        derived: d,
      })
    : "";
  const errSub = $("tile-error-sub");
  errSub.textContent = `${fmt.int(g.total_errors)} of ${fmt.compact(
    g.total_requests
  )} since reset`;
  errSub.className = "tile-sub " + (rate > 5 ? "is-bad" : "is-good");

  /* Latency — absent from the counters entirely; derived from the sample. */
  if (d && d.latencySamples) {
    setPulseValue("tile-latency-value", fmt.latency(d.p95));
    $("tile-latency-spark").innerHTML = sparkBars(d.latencyTrend, {
      tone: "accent",
      label: "p95",
      format: fmt.latency,
      derived: d,
    });
    $("tile-latency-sub").textContent = `median ${fmt.latency(
      d.p50
    )} · p99 ${fmt.latency(d.p99)}`;
  } else {
    setPulseValue("tile-latency-value", "—");
    $("tile-latency-spark").innerHTML = "";
    $("tile-latency-sub").textContent = "no latency samples yet";
  }

  /* Pressure — rate-limit and queue events are counters only, with no
     per-event history, so this tile shows a split rather than a fake trend. */
  setPulseValue(
    "tile-pressure-value",
    fmt.compact(g.total_rate_limit_hits),
    fmt.int(g.total_rate_limit_hits)
  );
  const limited = g.total_rate_limit_hits || 0;
  const queued = g.total_queue_hits || 0;
  const pressureTotal = limited + queued;
  $("tile-pressure-spark").innerHTML = pressureTotal
    ? `<div class="split-bar" role="img" aria-label="${fmt.int(
        limited
      )} rate-limited, ${fmt.int(queued)} queued">
         <span class="split-seg seg-limited" style="flex-grow:${limited}" title="${fmt.int(
        limited
      )} rate-limited"></span>
         <span class="split-seg seg-queued" style="flex-grow:${queued}" title="${fmt.int(
        queued
      )} queued"></span>
       </div>`
    : `<div class="split-bar is-empty" aria-hidden="true"></div>`;
  $("tile-pressure-sub").textContent = `${fmt.int(queued)} queued since reset`;
}

/* --- Band C: response health ------------------------------------------------ */

function renderHorizon() {
  const bar = $("horizon-bar");
  const legend = $("horizon-legend");
  const apis = (state.metrics && state.metrics.apis) || {};

  const totals = { "2xx": 0, "4xx": 0, "5xx": 0, other: 0 };
  for (const a of Object.values(apis)) {
    for (const [code, count] of Object.entries(a.responses || {})) {
      totals[statusClass(code)] += count;
    }
  }
  const total = STATUS_CLASSES.reduce((sum, c) => sum + totals[c], 0);

  if (!total) {
    if (!state.sections.metrics.attempted && !state.metrics) return;
    bar.className = "horizon-bar empty";
    bar.innerHTML = "";
    bar.setAttribute("aria-label", "Status mix: no responses yet");
    legend.textContent = "No responses yet.";
    return;
  }

  bar.className = "horizon-bar";
  bar.innerHTML = STATUS_CLASSES.filter((c) => totals[c] > 0)
    .map(
      (c) =>
        `<div class="hz-seg c${c}" style="flex-grow:${totals[c]}" title="${fmt.int(
          totals[c]
        )} ${c} responses"></div>`
    )
    .join("");

  const parts = STATUS_CLASSES.filter((c) => totals[c] > 0).map((c) => ({
    cls: c,
    pct: ((totals[c] / total) * 100).toFixed(1),
    count: totals[c],
  }));
  bar.setAttribute(
    "aria-label",
    "Status mix: " + parts.map((p) => `${p.cls} ${p.pct}%`).join(", ")
  );
  legend.innerHTML = parts
    .map(
      (p) =>
        `<span class="hz-key c${p.cls}" title="${fmt.int(
          p.count
        )} responses"><i aria-hidden="true"></i>${p.cls}<strong>${p.pct}%</strong></span>`
    )
    .join("");
}

function renderLatency() {
  const d = state.derived;
  $("latency-axis").innerHTML = latencyChartHtml(d);
  $("latency-sample").textContent = d
    ? `${fmt.compact(d.latencySamples)} recent responses`
    : "recent responses";
}

/* --- Band D: credential health ---------------------------------------------- */

function keyRowHtml(k, maxTotal, totalSum) {
  const share = totalSum ? (k.total / totalSum) * 100 : 0;
  const width = maxTotal ? (k.total / maxTotal) * 100 : 0;
  const selected = state.historyKey === k.id;
  // The bar's length carries share of pool; its colour is reserved for
  // credentials that are actually in trouble, so a key failing 1% of calls
  // does not read as loudly as one failing a third of them.
  const tone =
    k.errorRate > 25 ? "is-bad" : k.errorRate > 5 ? "is-warn" : "is-ok";
  const errText = k.recentTotal
    ? `${k.errorRate.toFixed(k.errorRate >= 10 ? 0 : 1)}%`
    : "—";

  return `<button type="button" class="key-row${selected ? " is-on" : ""}"
      data-key="${escapeHtml(k.id)}" data-focus-key="key:${escapeHtml(k.id)}"
      aria-pressed="${selected}"
      aria-label="Filter the traffic log by credential ${escapeHtml(k.id)}">
    <span class="key-id mono">${escapeHtml(k.id)}</span>
    <span class="key-track" aria-hidden="true">
      <span class="key-fill ${tone}" style="width:${width.toFixed(1)}%"></span>
    </span>
    <span class="key-share" title="${fmt.int(
      k.total
    )} requests">${share.toFixed(share >= 10 ? 0 : 1)}%</span>
    <span class="key-err ${tone}" title="${
      k.recentTotal
        ? `${fmt.int(k.recentErrors)} errors in ${fmt.int(
            k.recentTotal
          )} recent responses`
        : "No recent responses sampled for this credential"
    }">${errText}</span>
    <span class="key-last" title="${
      k.lastSeen ? new Date(k.lastSeen * 1000).toLocaleString() : "Not seen in the recent sample"
    }">${k.lastSeen ? fmt.ago(k.lastSeen) : "—"}</span>
  </button>`;
}

function renderKeys() {
  const wrap = $("key-board");
  const d = state.derived;
  const hasMetrics = !!(state.metrics && state.metrics.apis);

  if (!hasMetrics && !d) {
    const s = state.sections.metrics;
    if (!s.attempted) return; // keep skeleton
    wrap.innerHTML =
      s.failed && !s.lastSuccess
        ? `<div class="empty-state">${COIN_GLYPH}Couldn't load credential data — retrying automatically.</div>`
        : `<div class="empty-state">${COIN_GLYPH}No credentials used yet.</div>`;
    return;
  }

  const keys = (d && d.keys) || [];
  setCount("key-count", keys.length, `${fmt.int(keys.length)} credentials in use`);

  if (!keys.length) {
    wrap.innerHTML = `<div class="empty-state">${COIN_GLYPH}No credentials used yet — keys appear here once traffic flows.</div>`;
    return;
  }

  const maxTotal = Math.max(...keys.map((k) => k.total), 1);
  const totalSum = d.keyTotalSum || 0;
  const top = keys[0];
  const topShare = totalSum ? (top.total / totalSum) * 100 : 0;
  const failing = keys.filter((k) => k.recentTotal && k.errorRate > 25);

  // Concentration is the signal that matters for a rotation gateway: one key
  // carrying the pool tells you rotation is not doing its job.
  let note;
  if (keys.length === 1) {
    note = `A single credential is serving all traffic.`;
  } else if (topShare >= 60) {
    note = `<strong>${escapeHtml(top.id)}</strong> carries ${topShare.toFixed(
      0
    )}% of traffic across ${keys.length} credentials — rotation is uneven.`;
  } else {
    note = `Traffic spreads across ${keys.length} credentials; the busiest carries ${topShare.toFixed(
      0
    )}%.`;
  }
  if (failing.length) {
    note += ` ${failing.length} ${
      failing.length === 1 ? "credential is" : "credentials are"
    } failing more than a quarter of recent requests.`;
  }

  const html = `<div class="key-legend">
      <span class="key-id">Credential</span>
      <span class="key-track">Share of pool</span>
      <span class="key-share">%</span>
      <span class="key-err">Err</span>
      <span class="key-last">Last</span>
    </div>
    <div class="key-list">${keys
      .map((k) => keyRowHtml(k, maxTotal, totalSum))
      .join("")}</div>
    <p class="key-note">${note}</p>`;

  withFocusRestore(wrap, () => (wrap.innerHTML = html));
}

/* --- Band E: APIs ledger ----------------------------------------------------- */

function detailId(name) {
  return "api-detail-" + slug(name);
}

function detailRowHtml(name, a) {
  const d = state.derived;
  const trend = d && d.apis[name];
  const statusRows = Object.entries(a.responses || {})
    .sort((x, y) => y[1] - x[1])
    .map(
      ([code, n]) =>
        `<tr><td class="cell-muted"><span class="badge ${
          BADGE_BY_CLASS[statusClass(code)]
        }">${escapeHtml(code)}</span></td><td class="cell-num">${fmt.int(
          n
        )}</td></tr>`
    )
    .join("");
  const keyRows = Object.entries(a.key_usage || {})
    .sort((x, y) => y[1] - x[1])
    .map(
      ([key, n]) =>
        `<tr><td class="mono cell-muted">${escapeHtml(
          key
        )}</td><td class="cell-num">${fmt.int(n)}</td></tr>`
    )
    .join("");

  return `<tr class="detail-row" id="${detailId(name)}"><td colspan="9">
    <div class="detail-band">
      <div class="detail-head">
        <h3 class="detail-title">${escapeHtml(name)}</h3>
        <button type="button" class="link-btn view-traffic-btn" data-api="${escapeHtml(
          name
        )}">View in traffic log</button>
      </div>
      <dl class="kv">
        <dt>Total requests</dt><dd>${fmt.int(a.requests)}</dd>
        <dt>Errors</dt><dd>${fmt.int(a.errors)}</dd>
        <dt>Active requests</dt><dd>${fmt.int(a.active_requests)}</dd>
        <dt>Avg latency</dt><dd>${fmt.latency(a.avg_response_time_ms)}</dd>
        <dt>p95 latency <span class="dd-note">recent</span></dt><dd>${
          trend ? fmt.latency(trend.p95) : "—"
        }</dd>
        <dt>Rate-limit hits</dt><dd>${fmt.int(a.rate_limit_hits)}</dd>
        <dt>Queue hits</dt><dd>${fmt.int(a.queue_hits)}</dd>
        <dt>Last request</dt><dd>${fmt.ago(a.last_request_time)}</dd>
      </dl>
      ${
        statusRows || keyRows
          ? `<div class="detail-tables">
        ${
          statusRows
            ? `<div class="mini-table"><h4>Status codes</h4><table><tbody>${statusRows}</tbody></table></div>`
            : ""
        }
        ${
          keyRows
            ? `<div class="mini-table"><h4>Key usage</h4><table><tbody>${keyRows}</tbody></table></div>`
            : ""
        }
      </div>`
          : ""
      }
    </div>
  </td></tr>`;
}

function sortValue(name, a, queues, trend) {
  switch (state.sort.key) {
    case "requests":
      return a.requests || 0;
    case "errors":
      return a.requests ? (a.errors / a.requests) * 100 : 0;
    case "latency":
      return a.avg_response_time_ms || 0;
    case "p95":
      return trend ? trend.p95 : 0;
    case "active":
      return a.active_requests || 0;
    case "queue":
      return queues[name] || 0;
    case "last":
      return a.last_request_time || 0;
    default:
      return null; // name — compared as a string
  }
}

function renderSortHeaders() {
  for (const btn of document.querySelectorAll(".th-sort")) {
    const on = btn.dataset.sort === state.sort.key;
    btn.classList.toggle("is-sorted", on);
    btn.classList.toggle("is-asc", on && state.sort.dir === "asc");
    btn
      .closest("th")
      .setAttribute(
        "aria-sort",
        on ? (state.sort.dir === "asc" ? "ascending" : "descending") : "none"
      );
  }
}

function renderApis() {
  const body = $("api-tbody");
  const apis = (state.metrics && state.metrics.apis) || null;
  renderSortHeaders();

  if (!apis) {
    const s = state.sections.metrics;
    if (!s.attempted) return; // keep skeletons
    body.innerHTML =
      s.failed && !s.lastSuccess
        ? `<tr class="empty-row"><td colspan="9"><div class="empty-state">${COIN_GLYPH}Couldn't load API data — retrying automatically.</div></td></tr>`
        : `<tr class="empty-row"><td colspan="9"><div class="empty-state">${COIN_GLYPH}No traffic yet — requests will appear here.</div></td></tr>`;
    return;
  }

  // Drop the expansion (and its deep link) if a refresh removed the API.
  if (state.openApi && !apis[state.openApi]) {
    state.openApi = null;
    writeHash();
  }

  const allNames = Object.keys(apis);
  setCount("api-count", allNames.length, `${fmt.int(allNames.length)} APIs`);
  if (allNames.length === 0) {
    body.innerHTML = `<tr class="empty-row"><td colspan="9"><div class="empty-state">${COIN_GLYPH}No traffic yet — requests will appear here.</div></td></tr>`;
    return;
  }

  const queues = state.queues || {};
  const d = state.derived;
  const dir = state.sort.dir === "asc" ? 1 : -1;
  const names = allNames
    .filter((n) => n.toLowerCase().includes(state.apiFilter))
    .sort((x, y) => {
      if (state.sort.key === "name") return dir * x.localeCompare(y);
      const vx = sortValue(x, apis[x], queues, d && d.apis[x]);
      const vy = sortValue(y, apis[y], queues, d && d.apis[y]);
      return vx === vy ? x.localeCompare(y) : dir * (vx - vy);
    });

  if (names.length === 0) {
    body.innerHTML = `<tr class="empty-row"><td colspan="9"><div class="empty-state">No APIs match “${escapeHtml(
      state.apiFilter
    )}”.
      <button type="button" class="link-btn clear-filter-btn">Clear filter</button></div></td></tr>`;
    return;
  }

  const maxReq = Math.max(...names.map((n) => apis[n].requests || 0), 1);

  const html = names
    .map((name) => {
      const a = apis[name];
      const trend = d && d.apis[name];
      const rate = a.requests ? (a.errors / a.requests) * 100 : 0;
      const kind = rate > 5 ? "badge-err" : rate > 0 ? "badge-warn" : "badge-ok";
      const open = state.openApi === name;
      const qSize = queues[name];
      const pct = ((a.requests || 0) / maxReq) * 100;
      const row = `<tr class="api-row${
        open ? " is-open" : ""
      }" data-api="${escapeHtml(name)}">
        <td class="cell-name">
          <button type="button" class="chevron" data-api="${escapeHtml(name)}"
            data-focus-key="chev:${escapeHtml(name)}"
            aria-expanded="${open}" aria-controls="${detailId(name)}"
            aria-label="Details for ${escapeHtml(name)}">${CHEVRON_SVG}</button>${escapeHtml(
        name
      )}
        </td>
        <td class="cell-num cell-req">${fmt.int(
          a.requests
        )}<span class="prop-fill" style="width:${pct.toFixed(
        1
      )}%" aria-hidden="true"></span></td>
        <td class="cell-trend">${
          trend && trend.total
            ? sparkBars(trend.series, {
                tone: "accent",
                label: "responses",
                format: (v) => fmt.int(Math.round(v)),
                derived: d,
              })
            : `<span class="trend-empty" title="No responses in the recent sample">—</span>`
        }</td>
        <td class="cell-num"><span class="badge ${kind}">${rate.toFixed(
        1
      )}%</span></td>
        <td class="cell-num">${fmt.latency(a.avg_response_time_ms)}</td>
        <td class="cell-num cell-muted">${
          trend ? fmt.latency(trend.p95) : "—"
        }</td>
        <td class="cell-num">${
          a.active_requests
            ? `<span class="live-count">${fmt.int(a.active_requests)}</span>`
            : "—"
        }</td>
        <td class="cell-num">${qSize ? fmt.int(qSize) : "—"}</td>
        <td class="cell-num cell-muted">${fmt.ago(a.last_request_time)}</td>
      </tr>`;
      return open ? row + detailRowHtml(name, apis[name]) : row;
    })
    .join("");

  withFocusRestore(body, () => (body.innerHTML = html));

  // Restore scroll position for a deep-linked expansion, once.
  if (state.openApi && !state.restoredFromHash) {
    const band = document.getElementById(detailId(state.openApi));
    if (band) band.scrollIntoView({ block: "nearest" });
  }
  state.restoredFromHash = true;

  return names.length;
}

function toggleApi(name) {
  const opening = state.openApi !== name;
  state.openApi = opening ? name : null;
  writeHash(opening);
  renderApis();
}

/* --- Band F: queue strip ------------------------------------------------------ */

function queueChipHtml(name, size, controlEnabled) {
  const armed = state.confirm === "queue:" + name;
  let controls = "";
  if (controlEnabled) {
    controls = armed
      ? `<button type="button" class="chip-clear confirming" data-queue="${escapeHtml(
          name
        )}"
           data-focus-key="qclear:${escapeHtml(name)}"
           aria-label="Confirm: clear ${escapeHtml(name)} queue">Clear?</button>
         <button type="button" class="chip-cancel" data-queue="${escapeHtml(
           name
         )}"
           data-focus-key="qcancel:${escapeHtml(name)}"
           aria-label="Cancel clear ${escapeHtml(name)} queue">Cancel</button>`
      : `<button type="button" class="chip-clear" data-queue="${escapeHtml(
          name
        )}"
           data-focus-key="qclear:${escapeHtml(name)}"
           aria-label="Clear ${escapeHtml(name)} queue">clear</button>`;
  }
  return `<span class="chip" title="${size} requests queued">
    <span class="dot dot-warn" aria-hidden="true"></span><span class="chip-name">${escapeHtml(
      name
    )}</span>
    <span class="chip-count">${fmt.int(
      size
    )}</span><span class="chip-actions">${controls}</span></span>`;
}

function renderQueues() {
  const wrap = $("queue-strip");
  const q = state.queues;

  if (q === null) {
    const s = state.sections.queues;
    if (!s.attempted) return; // keep skeleton
    wrap.innerHTML =
      s.failed && !s.lastSuccess
        ? `<div class="empty-state">${COIN_GLYPH}Couldn't load queue data — retrying automatically.</div>`
        : `<div class="empty-state">${COIN_GLYPH}No queues configured.</div>`;
    return;
  }

  const names = Object.keys(q).sort((a, b) => a.localeCompare(b));
  const queued = names.reduce(
    (sum, name) => sum + Math.max(0, Number(q[name]) || 0),
    0
  );
  setCount("queue-count", queued, `${fmt.int(queued)} requests queued`);
  if (names.length === 0) {
    wrap.innerHTML = `<div class="empty-state">${COIN_GLYPH}No queues configured.</div>`;
    return;
  }

  const active = names.filter((n) => q[n] > 0);
  const idle = names.filter((n) => !(q[n] > 0));
  const controlEnabled = document.body.dataset.control === "flex";

  let html = active.map((n) => queueChipHtml(n, q[n], controlEnabled)).join("");
  if (idle.length) {
    const label =
      active.length === 0
        ? `All queues idle (${idle.length})`
        : `all other queues idle (${idle.length})`;
    html += `<button type="button" class="idle-disclosure" data-focus-key="idle-disclosure"
      aria-expanded="${state.idleOpen}">${label}</button>`;
    if (state.idleOpen) {
      html += `<div class="idle-list">${idle.map(escapeHtml).join(" · ")}</div>`;
    }
  }

  withFocusRestore(wrap, () => (wrap.innerHTML = html));
}

/* --- Band G: recent requests --------------------------------------------------- */

function renderChips(counts, total) {
  const wrap = $("status-chips");
  const defs = [["all", `All (${fmt.int(total)})`]].concat(
    STATUS_CLASSES.map((c) => [c, `${c} (${fmt.int(counts[c] || 0)})`])
  );
  withFocusRestore(wrap, () => {
    wrap.innerHTML = defs
      .map(
        ([cls, label]) =>
          `<button type="button" class="chip-filter${
            state.statusChip === cls ? " is-on" : ""
          }"
            data-class="${cls}" data-focus-key="chip:${cls}"
            aria-pressed="${state.statusChip === cls}">${label}</button>`
      )
      .join("");
  });
}

function renderActiveFilters() {
  const bar = $("active-filters");
  const chips = [];
  if (state.historyApi)
    chips.push({ kind: "api", label: "API", value: state.historyApi });
  if (state.historyKey)
    chips.push({ kind: "key", label: "Key", value: state.historyKey });

  if (!chips.length) {
    bar.hidden = true;
    bar.innerHTML = "";
    return;
  }
  bar.hidden = false;
  bar.innerHTML =
    chips
      .map(
        (c) =>
          `<span class="filter-tag">${c.label}
        <strong class="${c.kind === "key" ? "mono" : ""}">${escapeHtml(
            c.value
          )}</strong>
        <button type="button" class="filter-x" data-clear="${c.kind}"
          aria-label="Remove the ${c.label} filter">×</button></span>`
      )
      .join("") +
    `<button type="button" class="link-btn clear-all-filters">Clear all</button>`;
}

function renderHistory() {
  const body = $("history-tbody");
  renderActiveFilters();

  if (state.history === null) {
    const s = state.sections.history;
    if (!s.attempted) return; // keep skeletons
    if (s.failed && !s.lastSuccess) {
      body.innerHTML = `<tr class="empty-row"><td colspan="5"><div class="empty-state">${COIN_GLYPH}Couldn't load request history — retrying automatically.</div></td></tr>`;
      return 0;
    }
  }

  const responses = (state.history || []).filter((e) => e.type === "response");
  setCount(
    "history-count",
    responses.length,
    `${fmt.int(responses.length)} recent responses`
  );

  const counts = { "2xx": 0, "4xx": 0, "5xx": 0, other: 0 };
  for (const e of responses) counts[statusClass(e.status_code)] += 1;
  renderChips(counts, responses.length);

  if (responses.length === 0) {
    body.innerHTML = `<tr class="empty-row"><td colspan="5"><div class="empty-state">${COIN_GLYPH}No requests yet.</div></td></tr>`;
    return 0;
  }

  const filter = state.historyFilter;
  const rows = responses
    .filter(
      (e) =>
        state.statusChip === "all" ||
        statusClass(e.status_code) === state.statusChip
    )
    .filter((e) => !state.historyApi || e.api_name === state.historyApi)
    .filter((e) => !state.historyKey || e.key_id === state.historyKey)
    .filter(
      (e) =>
        !filter ||
        [e.api_name, e.status_code, e.key_id, fmt.time(e.timestamp)].some((v) =>
          String(v ?? "")
            .toLowerCase()
            .includes(filter)
        )
    )
    .slice(-HISTORY_LIMIT)
    .reverse();

  if (rows.length === 0) {
    const label = filter
      ? `No matches for “${escapeHtml(filter)}”.`
      : `No responses match the current filters.`;
    body.innerHTML = `<tr class="empty-row"><td colspan="5"><div class="empty-state">${label}
      <button type="button" class="link-btn clear-search-btn">Clear filters</button></div></td></tr>`;
    return 0;
  }

  // Latency bars are scaled against the slowest response on screen, so the
  // column reads as a comparison within the current view.
  const maxLatency = Math.max(...rows.map((e) => e.elapsed_ms || 0), 1);

  body.innerHTML = rows
    .map((e) => {
      const cls = statusClass(e.status_code);
      const lat = e.elapsed_ms || 0;
      return `<tr>
        <td class="cell-time">${fmt.time(e.timestamp)}</td>
        <td><button type="button" class="cell-link" data-filter-api="${escapeHtml(
          e.api_name
        )}" title="Filter the log by ${escapeHtml(
        e.api_name
      )}">${escapeHtml(e.api_name)}</button></td>
        <td><span class="badge ${BADGE_BY_CLASS[cls]}">${escapeHtml(
        e.status_code
      )}</span></td>
        <td class="cell-num cell-latency">
          <span class="lat-value">${fmt.latency(lat)}</span>
          <span class="lat-bar c${cls}" style="width:${(
            (lat / maxLatency) *
            100
          ).toFixed(1)}%" aria-hidden="true"></span>
        </td>
        <td><button type="button" class="cell-link mono" data-filter-key="${escapeHtml(
          e.key_id
        )}" title="Filter the log by ${escapeHtml(
        e.key_id
      )}">${escapeHtml(e.key_id)}</button></td>
      </tr>`;
    })
    .join("");

  return rows.length;
}

/* --- stamp & per-section status ------------------------------------------------ */

function renderStamp() {
  const el = $("last-updated");
  const connection = $("connection-status");
  const connectionLabel = $("connection-label");
  const secs = Object.values(state.sections);
  const succeeded = secs.map((s) => s.lastSuccess).filter(Boolean);
  if (!succeeded.length) {
    el.textContent = "";
    connection.className = "status-pill is-stale";
    connection.querySelector(".dot").className = "dot dot-warn";
    connectionLabel.textContent = "Connecting";
    return;
  }
  const worst = Math.min(...succeeded);
  const anyFailed = secs.some((s) => s.failed);
  const stale = anyFailed || Date.now() - worst > 2 * BASE_REFRESH_MS + 5000;
  const rel = fmt.ago(worst / 1000);
  el.title = new Date(worst).toLocaleString();
  if (stale) {
    el.className = "stamp is-stale";
    el.innerHTML = `<span class="dot dot-warn" aria-hidden="true"></span>stale — last data ${rel}`;
    connection.className = "status-pill is-stale";
    connection.querySelector(".dot").className = "dot dot-warn";
    connectionLabel.textContent = "Degraded";
    if (!state.wasStale) announce("Dashboard data is stale");
    state.wasStale = true;
  } else {
    el.className = "stamp";
    el.textContent = `updated ${rel}`;
    connection.className = "status-pill";
    connection.querySelector(".dot").className = "dot dot-ok";
    connectionLabel.textContent = "Live";
    state.wasStale = false;
  }
}

function renderMicroStatus() {
  const map = {
    "ms-apis": "metrics",
    "ms-keys": "metrics",
    "ms-queues": "queues",
    "ms-history": "history",
  };
  for (const [id, key] of Object.entries(map)) {
    const el = $(id);
    const s = state.sections[key];
    if (s.failed) {
      el.hidden = false;
      el.title = s.lastSuccess
        ? `Couldn't refresh — showing data from ${fmt.ago(s.lastSuccess / 1000)}`
        : "Couldn't load — no data received yet";
    } else {
      el.hidden = true;
    }
  }
}

/* --- refresh loop ---------------------------------------------------------------- */

function renderAll() {
  renderIntroMeta();
  renderPulse();
  renderHorizon();
  renderLatency();
  renderKeys();
  renderApis();
  renderQueues();
  renderHistory();
  renderMicroStatus();
}

function scheduleNext() {
  clearTimeout(refreshTimer);
  if (document.hidden) return;
  refreshTimer = setTimeout(fetchAll, state.refreshMs);
}

async function fetchAll(manual = false) {
  if (state.inFlight) return; // in-flight guard
  state.inFlight = true;
  if (manual === true) state.refreshMs = BASE_REFRESH_MS; // manual resets backoff

  const btn = $("refresh-btn");
  btn.classList.add("busy");
  btn.setAttribute("aria-busy", "true");

  const jobs = [
    ["metrics", getJSON("/metrics")],
    ["history", getJSON("/history")],
    ["queues", getJSON("/queue")],
  ];
  const results = await Promise.allSettled(jobs.map((j) => j[1]));
  const now = Date.now();
  let anyFail = false;

  results.forEach((r, i) => {
    const key = jobs[i][0];
    const section = state.sections[key];
    section.attempted = true;
    if (r.status === "fulfilled") {
      section.failed = false;
      section.lastSuccess = now;
      if (key === "metrics") state.metrics = r.value;
      else if (key === "history") state.history = r.value.history || [];
      else state.queues = r.value.queue_sizes || {};
    } else {
      section.failed = true;
      anyFail = true;
      console.error(r.reason);
    }
  });

  state.derived = deriveAnalytics(state.history, state.metrics);

  if (anyFail) {
    state.failStreak += 1;
    state.refreshMs = Math.min(state.refreshMs * 2, MAX_REFRESH_MS);
    if (state.failStreak === 1)
      toast("Failed to refresh dashboard data", "error");
  } else {
    state.failStreak = 0;
    state.refreshMs = BASE_REFRESH_MS;
  }

  renderAll();
  renderStamp();

  state.inFlight = false;
  btn.classList.remove("busy");
  btn.removeAttribute("aria-busy");
  scheduleNext();
}

/* --- two-step destructive commits ------------------------------------------------- */

function disarmAll() {
  if (!state.confirm) return;
  const key = state.confirm;
  state.confirm = null;
  if (confirmReverters[key]) confirmReverters[key]();
  else if (key.startsWith("queue:")) renderQueues();
}

function bindConfirm(btnId, cancelId, { key, armedLabel, busyLabel, run }) {
  const btn = $(btnId);
  const cancel = $(cancelId);
  const restingLabel = btn.textContent.trim();

  function revert() {
    btn.textContent = restingLabel;
    btn.classList.remove("confirming");
    cancel.hidden = true;
  }
  confirmReverters[key] = revert;

  btn.addEventListener("click", async () => {
    if (btn.getAttribute("aria-busy") === "true") return;
    if (state.confirm !== key) {
      disarmAll(); // only one armed control at a time
      state.confirm = key;
      btn.textContent = armedLabel;
      btn.classList.add("confirming");
      cancel.hidden = false;
      return;
    }
    // second activation — execute
    state.confirm = null;
    revert();
    btn.setAttribute("aria-busy", "true");
    btn.textContent = busyLabel;
    try {
      await run();
    } finally {
      btn.removeAttribute("aria-busy");
      btn.textContent = restingLabel;
    }
  });

  cancel.addEventListener("click", () => {
    if (state.confirm === key) state.confirm = null;
    revert();
    btn.focus();
  });

  // focusout leaving the pair reverts (no timed auto-revert while focused)
  const group = btn.parentElement;
  group.addEventListener("focusout", () => {
    setTimeout(() => {
      if (state.confirm === key && !group.contains(document.activeElement)) {
        state.confirm = null;
        revert();
      }
    }, 0);
  });
}

/* --- theme ------------------------------------------------------------------------ */

function currentTheme() {
  return document.documentElement.getAttribute("data-theme") === "light"
    ? "light"
    : "dark";
}

function syncThemeUI() {
  const dark = currentTheme() === "dark";
  document.querySelector(".icon-moon").style.display = dark ? "" : "none";
  document.querySelector(".icon-sun").style.display = dark ? "none" : "";
  $("theme-toggle").setAttribute(
    "aria-label",
    dark ? "Switch to light theme" : "Switch to dark theme"
  );
}

function toggleTheme() {
  // Enable the 120 ms ease only after an explicit toggle — never on load.
  document.documentElement.classList.add("theme-transition");
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try {
    localStorage.setItem("nyaproxy-theme", next); // stored only on explicit toggle
  } catch {}
  syncThemeUI();
}

/* --- cross-filtering --------------------------------------------------------------- */

function setHistoryApi(name) {
  state.historyApi = state.historyApi === name ? null : name;
  const n = renderHistory();
  announce(`${n ?? 0} requests shown`);
}

function setHistoryKey(id) {
  state.historyKey = state.historyKey === id ? null : id;
  writeHash();
  const n = renderHistory();
  renderKeys();
  announce(`${n ?? 0} requests shown`);
}

function clearHistoryFilters() {
  state.historyApi = null;
  state.historyKey = null;
  state.historyFilter = "";
  state.statusChip = "all";
  $("history-search").value = "";
  writeHash();
  renderHistory();
  renderKeys();
}

function scrollToHistory() {
  document
    .getElementById("activity")
    .scrollIntoView({ behavior: "smooth", block: "start" });
}

/* --- event wiring ------------------------------------------------------------------ */

function wireApiTable() {
  $("api-tbody").addEventListener("click", (e) => {
    const clear = e.target.closest(".clear-filter-btn");
    if (clear) {
      state.apiFilter = "";
      $("api-search").value = "";
      renderApis();
      $("api-search").focus();
      return;
    }
    const view = e.target.closest(".view-traffic-btn");
    if (view) {
      state.historyApi = view.dataset.api;
      renderHistory();
      scrollToHistory();
      return;
    }
    const row = e.target.closest("tr.api-row");
    if (row) toggleApi(row.dataset.api);
  });

  for (const btn of document.querySelectorAll(".th-sort")) {
    btn.addEventListener("click", () => {
      const key = btn.dataset.sort;
      if (state.sort.key === key) {
        state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
      } else {
        state.sort.key = key;
        // Names read naturally A→Z; every measure is most useful highest-first.
        state.sort.dir = key === "name" ? "asc" : "desc";
      }
      renderApis();
    });
  }
}

function wireKeyBoard() {
  $("key-board").addEventListener("click", (e) => {
    const row = e.target.closest(".key-row");
    if (!row) return;
    setHistoryKey(row.dataset.key);
    scrollToHistory();
  });
}

function wireQueueStrip() {
  const strip = $("queue-strip");
  strip.addEventListener("click", async (e) => {
    const disclosure = e.target.closest(".idle-disclosure");
    if (disclosure) {
      state.idleOpen = !state.idleOpen;
      renderQueues();
      return;
    }
    const cancel = e.target.closest(".chip-cancel");
    if (cancel) {
      state.confirm = null;
      renderQueues();
      focusKey("qclear:" + cancel.dataset.queue);
      return;
    }
    const clearBtn = e.target.closest(".chip-clear");
    if (!clearBtn) return;
    const name = clearBtn.dataset.queue;
    const key = "queue:" + name;
    if (state.confirm !== key) {
      disarmAll();
      state.confirm = key;
      renderQueues();
      focusKey("qclear:" + name);
      return;
    }
    // second activation — execute
    state.confirm = null;
    clearBtn.setAttribute("aria-busy", "true");
    clearBtn.textContent = "Clearing…";
    try {
      const res = await postJSON("/queue/clear/" + encodeURIComponent(name));
      toast(`Cleared ${res.cleared_count ?? 0} queued requests`);
    } catch (err) {
      console.error(err);
      toast("Failed to clear queue", "error");
    }
    fetchAll();
  });

  strip.addEventListener("focusout", () => {
    setTimeout(() => {
      if (
        state.confirm &&
        state.confirm.startsWith("queue:") &&
        !strip.contains(document.activeElement)
      ) {
        state.confirm = null;
        renderQueues();
      }
    }, 0);
  });
}

function wireHistory() {
  $("status-chips").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip-filter");
    if (!chip) return;
    state.statusChip = chip.dataset.class;
    writeHash();
    const n = renderHistory();
    announce(`${n ?? 0} requests shown`);
  });

  $("active-filters").addEventListener("click", (e) => {
    if (e.target.closest(".clear-all-filters")) {
      clearHistoryFilters();
      announce("Filters cleared");
      return;
    }
    const x = e.target.closest(".filter-x");
    if (!x) return;
    if (x.dataset.clear === "api") state.historyApi = null;
    else state.historyKey = null;
    writeHash();
    renderHistory();
    renderKeys();
  });

  $("history-tbody").addEventListener("click", (e) => {
    if (e.target.closest(".clear-search-btn")) {
      clearHistoryFilters();
      $("history-search").focus();
      return;
    }
    const apiBtn = e.target.closest("[data-filter-api]");
    if (apiBtn) {
      setHistoryApi(apiBtn.dataset.filterApi);
      return;
    }
    const keyBtn = e.target.closest("[data-filter-key]");
    if (keyBtn) setHistoryKey(keyBtn.dataset.filterKey);
  });

  $("history-search").addEventListener("input", (e) => {
    state.historyFilter = e.target.value.trim().toLowerCase();
    const n = renderHistory();
    announce(`${n ?? 0} requests shown`);
  });
}

function wireShortcuts() {
  document.addEventListener("keydown", (e) => {
    const tag = e.target.tagName;
    const inField = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";

    if (e.key === "Escape") {
      if (inField) return;
      if (state.confirm) {
        disarmAll();
        return;
      }
      if (state.historyApi || state.historyKey) {
        clearHistoryFilters();
        return;
      }
      if (state.openApi) {
        const name = state.openApi;
        state.openApi = null;
        writeHash();
        renderApis();
        focusKey("chev:" + name);
        return;
      }
      if (state.idleOpen) {
        state.idleOpen = false;
        renderQueues();
        focusKey("idle-disclosure");
      }
      return;
    }

    if (inField || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "/") {
      e.preventDefault();
      $("api-search").focus();
    } else if (e.key === "r") {
      fetchAll(true);
    }
  });
}

/* --- init -------------------------------------------------------------------------- */

function init() {
  syncThemeUI();
  $("theme-toggle").addEventListener("click", toggleTheme);
  $("refresh-btn").addEventListener("click", () => fetchAll(true));

  bindConfirm("reset-metrics-btn", "reset-metrics-cancel", {
    key: "reset-metrics",
    armedLabel: "Reset metrics?",
    busyLabel: "Resetting…",
    run: async () => {
      try {
        await postJSON("/metrics/reset");
        toast("Metrics reset");
        fetchAll();
      } catch (err) {
        console.error(err);
        toast("Failed to reset metrics", "error");
      }
    },
  });

  bindConfirm("clear-all-queues-btn", "clear-all-queues-cancel", {
    key: "clear-all-queues",
    armedLabel: "Clear all queues?",
    busyLabel: "Clearing…",
    run: async () => {
      try {
        const res = await postJSON("/queue/clear");
        toast(`Cleared ${res.cleared_count ?? 0} queued requests`);
        fetchAll();
      } catch (err) {
        console.error(err);
        toast("Failed to clear queues", "error");
      }
    },
  });

  $("api-search").addEventListener("input", (e) => {
    state.apiFilter = e.target.value.trim().toLowerCase();
    const n = renderApis();
    announce(`${n ?? 0} APIs shown`);
  });

  wireApiTable();
  wireKeyBoard();
  wireQueueStrip();
  wireHistory();
  wireShortcuts();

  // Deep links: restore #api=<name> / #status=<class> / #key=<id> first.
  const h = readHash();
  state.openApi = h.api;
  state.statusChip = h.status;
  state.historyKey = h.key;
  window.addEventListener("hashchange", onHashChange);

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearTimeout(refreshTimer);
    else fetchAll(); // refresh immediately, then restart the cadence
  });

  setInterval(renderStamp, 5000); // text-only relative-time re-render

  fetchAll();
}

document.addEventListener("DOMContentLoaded", init);
