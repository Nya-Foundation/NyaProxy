/* ===========================================================================
 * NyaProxy dashboard — "Coin Cat" UI.
 *
 * Dependency-free client. Polls the dashboard JSON API every 15 s and
 * re-renders each band from cached state; expansion, filters, and confirm
 * states key on state (not DOM), so every render is idempotent.
 * ========================================================================= */
"use strict";

/* --- constants ------------------------------------------------------------ */

const API = new URL("api", new URL(".", window.location.href)).href;
const BASE_REFRESH_MS = 15000;
const MAX_REFRESH_MS = 60000;
const HISTORY_LIMIT = 60;
const STATUS_CLASSES = ["2xx", "4xx", "5xx", "other"];

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
  apiFilter: "",
  historyFilter: "",
  statusChip: "all",
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
};

function statusClass(code) {
  const c = Number(code);
  if (c >= 200 && c < 300) return "2xx";
  if (c >= 400 && c < 500) return "4xx";
  if (c >= 500) return "5xx";
  return "other";
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

/* --- URL hash (deep links: #api=<name>&status=<class>) --------------------- */

function readHash() {
  const out = { api: null, status: "all" };
  for (const part of window.location.hash.replace(/^#/, "").split("&")) {
    const eq = part.indexOf("=");
    if (eq < 0) continue;
    const k = part.slice(0, eq);
    const v = part.slice(eq + 1);
    if (k === "api" && v) {
      try {
        out.api = decodeURIComponent(v);
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
  if (["#overview", "#apis", "#activity"].includes(window.location.hash)) return;
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
  if (apisDirty) renderApis();
  if (historyDirty) renderHistory();
}

/* --- Band B: pulse row ----------------------------------------------------- */

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
  if (!g) {
    if (!state.sections.metrics.attempted) return;
    for (const id of [
      "tile-error-value",
      "tile-requests-value",
      "tile-pressure-value",
      "tile-uptime-value",
    ])
      setPulseValue(id, "—");
    return;
  }

  const rate = g.total_requests
    ? (g.total_errors / g.total_requests) * 100
    : 0;
  setPulseValue("tile-error-value", `${rate.toFixed(2)}%`);
  const dot = $("tile-error-dot");
  dot.hidden = false;
  dot.className = "dot " + (rate > 5 ? "dot-err" : "dot-ok");
  const errSub = $("tile-error-sub");
  errSub.textContent = `${fmt.int(g.total_errors)} errors`;
  errSub.className = "tile-sub " + (rate > 5 ? "is-bad" : "is-good");

  setPulseValue(
    "tile-requests-value",
    fmt.compact(g.total_requests),
    fmt.int(g.total_requests)
  );
  setPulseValue(
    "tile-pressure-value",
    fmt.compact(g.total_rate_limit_hits),
    fmt.int(g.total_rate_limit_hits)
  );
  $("tile-pressure-sub").textContent = `${fmt.int(g.total_queue_hits)} queued`;
  setPulseValue("tile-uptime-value", fmt.duration(g.uptime_seconds));
}

/* --- Band C: horizon bar ---------------------------------------------------- */

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
        `<div class="hz-seg c${c}" style="flex-grow:${totals[c]}"></div>`
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
        `<span class="hz-key c${p.cls}" title="${p.count} responses"><i aria-hidden="true"></i>${p.cls}<strong>${p.pct}%</strong></span>`
    )
    .join("");
}

/* --- Band D: APIs ledger ----------------------------------------------------- */

function detailId(name) {
  return "api-detail-" + slug(name);
}

function detailRowHtml(name, a) {
  const statusRows = Object.entries(a.responses || {})
    .sort((x, y) => y[1] - x[1])
    .map(
      ([code, n]) =>
        `<tr><td class="cell-muted">HTTP ${escapeHtml(code)}</td><td class="cell-num">${fmt.int(n)}</td></tr>`
    )
    .join("");
  const keyRows = Object.entries(a.key_usage || {})
    .sort((x, y) => y[1] - x[1])
    .map(
      ([key, n]) =>
        `<tr><td class="mono cell-muted">${escapeHtml(key)}</td><td class="cell-num">${fmt.int(n)}</td></tr>`
    )
    .join("");

  return `<tr class="detail-row" id="${detailId(name)}"><td colspan="7">
    <div class="detail-band">
      <h3 class="detail-title">${escapeHtml(name)}</h3>
      <dl class="kv">
        <dt>Total requests</dt><dd>${fmt.int(a.requests)}</dd>
        <dt>Errors</dt><dd>${fmt.int(a.errors)}</dd>
        <dt>Active requests</dt><dd>${fmt.int(a.active_requests)}</dd>
        <dt>Avg latency</dt><dd>${fmt.latency(a.avg_response_time_ms)}</dd>
        <dt>Rate-limit hits</dt><dd>${fmt.int(a.rate_limit_hits)}</dd>
        <dt>Queue hits</dt><dd>${fmt.int(a.queue_hits)}</dd>
        <dt>Last request</dt><dd>${fmt.ago(a.last_request_time)}</dd>
      </dl>
      ${
        statusRows || keyRows
          ? `<div class="detail-tables">
        ${statusRows ? `<div class="mini-table"><h4>Status codes</h4><table><tbody>${statusRows}</tbody></table></div>` : ""}
        ${keyRows ? `<div class="mini-table"><h4>Key usage</h4><table><tbody>${keyRows}</tbody></table></div>` : ""}
      </div>`
          : ""
      }
    </div>
  </td></tr>`;
}

function renderApis() {
  const body = $("api-tbody");
  const apis = (state.metrics && state.metrics.apis) || null;

  if (!apis) {
    const s = state.sections.metrics;
    if (!s.attempted) return; // keep skeletons
    body.innerHTML =
      s.failed && !s.lastSuccess
        ? `<tr class="empty-row"><td colspan="7"><div class="empty-state">${COIN_GLYPH}Couldn't load API data — retrying automatically.</div></td></tr>`
        : `<tr class="empty-row"><td colspan="7"><div class="empty-state">${COIN_GLYPH}No traffic yet — requests will appear here.</div></td></tr>`;
    return;
  }

  // Drop the expansion (and its deep link) if a refresh removed the API.
  if (state.openApi && !apis[state.openApi]) {
    state.openApi = null;
    writeHash();
  }

  const allNames = Object.keys(apis).sort((a, b) => a.localeCompare(b));
  setCount("api-count", allNames.length, `${fmt.int(allNames.length)} APIs`);
  if (allNames.length === 0) {
    body.innerHTML = `<tr class="empty-row"><td colspan="7"><div class="empty-state">${COIN_GLYPH}No traffic yet — requests will appear here.</div></td></tr>`;
    return;
  }

  const names = allNames.filter((n) =>
    n.toLowerCase().includes(state.apiFilter)
  );
  if (names.length === 0) {
    body.innerHTML = `<tr class="empty-row"><td colspan="7"><div class="empty-state">No APIs match “${escapeHtml(state.apiFilter)}”.
      <button type="button" class="link-btn clear-filter-btn">Clear filter</button></div></td></tr>`;
    return;
  }

  const maxReq = Math.max(...names.map((n) => apis[n].requests || 0), 1);
  const queues = state.queues || {};

  const html = names
    .map((name) => {
      const a = apis[name];
      const rate = a.requests ? (a.errors / a.requests) * 100 : 0;
      const kind =
        rate > 5 ? "badge-err" : rate > 0 ? "badge-warn" : "badge-ok";
      const open = state.openApi === name;
      const qSize = queues[name];
      const pct = ((a.requests || 0) / maxReq) * 100;
      const row = `<tr class="api-row${open ? " is-open" : ""}" data-api="${escapeHtml(name)}">
        <td class="cell-name">
          <button type="button" class="chevron" data-api="${escapeHtml(name)}"
            data-focus-key="chev:${escapeHtml(name)}"
            aria-expanded="${open}" aria-controls="${detailId(name)}"
            aria-label="Details for ${escapeHtml(name)}">${CHEVRON_SVG}</button>${escapeHtml(name)}
        </td>
        <td class="cell-num cell-req">${fmt.int(a.requests)}<span class="prop-fill" style="width:${pct.toFixed(1)}%" aria-hidden="true"></span></td>
        <td class="cell-num"><span class="badge ${kind}">${rate.toFixed(1)}%</span></td>
        <td class="cell-num">${fmt.latency(a.avg_response_time_ms)}</td>
        <td class="cell-num">${fmt.int(a.active_requests)}</td>
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

/* --- Band E: queue strip ------------------------------------------------------ */

function queueChipHtml(name, size, controlEnabled) {
  const armed = state.confirm === "queue:" + name;
  let controls = "";
  if (controlEnabled) {
    controls = armed
      ? `<button type="button" class="chip-clear confirming" data-queue="${escapeHtml(name)}"
           data-focus-key="qclear:${escapeHtml(name)}"
           aria-label="Confirm: clear ${escapeHtml(name)} queue">Clear?</button>
         <button type="button" class="chip-cancel" data-queue="${escapeHtml(name)}"
           data-focus-key="qcancel:${escapeHtml(name)}"
           aria-label="Cancel clear ${escapeHtml(name)} queue">Cancel</button>`
      : `<button type="button" class="chip-clear" data-queue="${escapeHtml(name)}"
           data-focus-key="qclear:${escapeHtml(name)}"
           aria-label="Clear ${escapeHtml(name)} queue">clear</button>`;
  }
  return `<span class="chip" title="${size} requests queued">
    <span class="dot dot-warn" aria-hidden="true"></span><span class="chip-name">${escapeHtml(name)}</span>
    <span class="chip-count">${fmt.int(size)}</span><span class="chip-actions">${controls}</span></span>`;
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
  const queued = names.reduce((sum, name) => sum + Math.max(0, Number(q[name]) || 0), 0);
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

/* --- Band F: recent requests --------------------------------------------------- */

function renderChips(counts, total) {
  const wrap = $("status-chips");
  const defs = [["all", `All (${fmt.int(total)})`]].concat(
    STATUS_CLASSES.map((c) => [c, `${c} (${fmt.int(counts[c] || 0)})`])
  );
  withFocusRestore(wrap, () => {
    wrap.innerHTML = defs
      .map(
        ([cls, label]) =>
          `<button type="button" class="chip-filter${state.statusChip === cls ? " is-on" : ""}"
            data-class="${cls}" data-focus-key="chip:${cls}"
            aria-pressed="${state.statusChip === cls}">${label}</button>`
      )
      .join("");
  });
}

function renderHistory() {
  const body = $("history-tbody");
  if (state.history === null) {
    const s = state.sections.history;
    if (!s.attempted) return; // keep skeletons
    if (s.failed && !s.lastSuccess) {
      body.innerHTML = `<tr class="empty-row"><td colspan="5"><div class="empty-state">${COIN_GLYPH}Couldn't load request history — retrying automatically.</div></td></tr>`;
      return 0;
    }
  }

  const responses = (state.history || []).filter((e) => e.type === "response");
  setCount("history-count", responses.length, `${fmt.int(responses.length)} recent responses`);

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
    .filter(
      (e) =>
        !filter ||
        [e.api_name, e.status_code, e.key_id, fmt.time(e.timestamp)].some(
          (v) =>
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
      : `No ${escapeHtml(state.statusChip)} responses.`;
    body.innerHTML = `<tr class="empty-row"><td colspan="5"><div class="empty-state">${label}
      <button type="button" class="link-btn clear-search-btn">Clear search</button></div></td></tr>`;
    return 0;
  }

  body.innerHTML = rows
    .map((e) => {
      const cls = statusClass(e.status_code);
      return `<tr>
        <td class="cell-time">${fmt.time(e.timestamp)}</td>
        <td>${escapeHtml(e.api_name)}</td>
        <td><span class="badge ${BADGE_BY_CLASS[cls]}">${escapeHtml(e.status_code)}</span></td>
        <td class="cell-num">${fmt.latency(e.elapsed_ms)}</td>
        <td class="mono cell-muted">${escapeHtml(e.key_id)}</td>
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
  const map = { "ms-apis": "metrics", "ms-queues": "queues", "ms-history": "history" };
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
  renderPulse();
  renderHorizon();
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
  if (manual === true) state.refreshMs = BASE_REFRESH_MS; // manual refresh resets backoff

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

  if (anyFail) {
    state.failStreak += 1;
    state.refreshMs = Math.min(state.refreshMs * 2, MAX_REFRESH_MS);
    if (state.failStreak === 1) toast("Failed to refresh dashboard data", "error");
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
    const row = e.target.closest("tr.api-row");
    if (row) toggleApi(row.dataset.api);
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

  $("history-tbody").addEventListener("click", (e) => {
    if (!e.target.closest(".clear-search-btn")) return;
    state.historyFilter = "";
    state.statusChip = "all";
    $("history-search").value = "";
    writeHash();
    renderHistory();
    $("history-search").focus();
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
  wireQueueStrip();
  wireHistory();
  wireShortcuts();

  // Deep links: restore #api=<name> / #status=<class> before the first fetch.
  const h = readHash();
  state.openApi = h.api;
  state.statusChip = h.status;
  window.addEventListener("hashchange", onHashChange);

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearTimeout(refreshTimer);
    else fetchAll(); // refresh immediately, then restart the cadence
  });

  setInterval(renderStamp, 5000); // text-only relative-time re-render

  fetchAll();
}

document.addEventListener("DOMContentLoaded", init);
