/* ===========================================================================
 * NyaProxy dashboard.
 *
 * A small, dependency-free client: it polls the dashboard JSON API and renders
 * current-state views. Time-series analysis lives in Prometheus/Grafana via
 * the `/metrics` endpoint — this UI deliberately only shows "right now".
 * ========================================================================= */
"use strict";

const API = new URL("api", new URL(".", window.location.href)).href;
const REFRESH_MS = 15000;

const state = {
  metrics: null,
  history: [],
  queues: {},
  apiFilter: "",
  historyFilter: "",
};

/* --- formatting ---------------------------------------------------------- */

const fmt = {
  number(n) {
    return (n || 0).toLocaleString("en-US");
  },
  latency(ms) {
    if (!ms) return "—";
    return ms >= 1000 ? (ms / 1000).toFixed(2) + " s" : Math.round(ms) + " ms";
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
    const delta = Date.now() / 1000 - epochSeconds;
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

function statusKind(code) {
  if (code >= 200 && code < 300) return "ok";
  if (code >= 400 && code < 500) return "warn";
  if (code >= 500) return "err";
  return "neutral";
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

const $ = (id) => document.getElementById(id);

/* --- API client ---------------------------------------------------------- */

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

/* --- toast --------------------------------------------------------------- */

let toastTimer = null;
function toast(message, kind = "ok") {
  const node = $("toast");
  $("toast-msg").textContent = message;
  node.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.className = "toast"), 3200);
}

/* --- rendering ----------------------------------------------------------- */

function renderStats(global) {
  $("stat-requests").textContent = fmt.number(global.total_requests);
  $("stat-errors").textContent = fmt.number(global.total_errors);
  $("stat-ratelimits").textContent = fmt.number(global.total_rate_limit_hits);
  $("stat-uptime").textContent = fmt.duration(global.uptime_seconds);

  const rate = global.total_requests
    ? (global.total_errors / global.total_requests) * 100
    : 0;
  const rateEl = $("stat-error-rate");
  rateEl.textContent = `${rate.toFixed(2)}% error rate`;
  rateEl.className = "stat-sub " + (rate > 5 ? "is-bad" : "is-good");

  $("stat-queue-hits").textContent =
    `${fmt.number(global.total_queue_hits)} queued`;
}

function renderApiTable(apis) {
  const names = Object.keys(apis)
    .filter((n) => n.toLowerCase().includes(state.apiFilter))
    .sort();
  const body = $("api-tbody");

  if (names.length === 0) {
    body.innerHTML =
      '<tr class="empty-row"><td colspan="8">No APIs match.</td></tr>';
    return;
  }

  body.innerHTML = names
    .map((name) => {
      const a = apis[name];
      const rate = a.requests ? (a.errors / a.requests) * 100 : 0;
      const kind = rate > 5 ? "badge-err" : rate > 0 ? "badge-warn" : "badge-ok";
      return `<tr>
        <td class="cell-name">${escapeHtml(name)}</td>
        <td>${fmt.number(a.requests)}</td>
        <td>${fmt.number(a.errors)}</td>
        <td><span class="badge ${kind}">${rate.toFixed(1)}%</span></td>
        <td>${fmt.latency(a.avg_response_time_ms)}</td>
        <td>${fmt.number(a.active_requests)}</td>
        <td class="cell-muted">${fmt.ago(a.last_request_time)}</td>
        <td><button class="row-action" data-api="${escapeHtml(name)}">Details</button></td>
      </tr>`;
    })
    .join("");

  body.querySelectorAll(".row-action").forEach((btn) => {
    btn.addEventListener("click", () => openModal(btn.dataset.api));
  });
}

function renderBars(container, rows) {
  if (rows.length === 0) {
    container.innerHTML = '<div class="skeleton">No data yet.</div>';
    return;
  }
  const max = Math.max(...rows.map((r) => r.value), 1);
  container.innerHTML = rows
    .map((r) => {
      const pct = (r.value / max) * 100;
      return `<div class="bar-row">
        <span class="bar-label">${escapeHtml(r.label)}</span>
        <span class="bar-track"><span class="bar-fill ${r.kind || ""}" style="width:${pct}%"></span></span>
        <span class="bar-value">${fmt.number(r.value)}</span>
      </div>`;
    })
    .join("");
}

function renderDistributions(apis) {
  // Status codes, aggregated across every API.
  const statusTotals = {};
  for (const a of Object.values(apis)) {
    for (const [code, count] of Object.entries(a.responses || {})) {
      statusTotals[code] = (statusTotals[code] || 0) + count;
    }
  }
  const statusRows = Object.entries(statusTotals)
    .map(([code, value]) => ({
      label: code,
      value,
      kind: statusKind(Number(code)),
    }))
    .sort((x, y) => y.value - x.value);
  renderBars($("dist-status"), statusRows);

  // Requests per API.
  const apiRows = Object.entries(apis)
    .map(([name, a]) => ({ label: name, value: a.requests }))
    .filter((r) => r.value > 0)
    .sort((x, y) => y.value - x.value);
  renderBars($("dist-api"), apiRows);
}

function renderQueues(queueSizes) {
  const names = Object.keys(queueSizes || {}).sort();
  const grid = $("queue-grid");

  if (names.length === 0) {
    grid.innerHTML = '<div class="queue-card skeleton">No active queues.</div>';
    return;
  }

  grid.innerHTML = names
    .map((name) => {
      const size = queueSizes[name];
      return `<div class="queue-card">
        <div class="qc-head">
          <span class="qc-name">${escapeHtml(name)}</span>
          <span class="badge ${size > 0 ? "badge-warn" : "badge-neutral"}">
            ${size > 0 ? "active" : "idle"}
          </span>
        </div>
        <div class="qc-value">${fmt.number(size)}</div>
        <div class="qc-label">requests queued</div>
      </div>`;
    })
    .join("");
}

function renderHistory(history) {
  const filter = state.historyFilter;
  const rows = history
    .filter((e) => e.type === "response")
    .filter((e) => !filter || JSON.stringify(e).toLowerCase().includes(filter))
    .slice(-60)
    .reverse();
  const body = $("history-tbody");

  if (rows.length === 0) {
    body.innerHTML =
      '<tr class="empty-row"><td colspan="5">No requests yet.</td></tr>';
    return;
  }

  body.innerHTML = rows
    .map((e) => {
      const kind = statusKind(e.status_code);
      return `<tr>
        <td class="cell-muted">${fmt.time(e.timestamp)}</td>
        <td>${escapeHtml(e.api_name)}</td>
        <td><span class="badge badge-${kind === "neutral" ? "neutral" : kind}">${e.status_code}</span></td>
        <td>${fmt.latency(e.elapsed_ms)}</td>
        <td class="mono cell-muted">${escapeHtml(e.key_id)}</td>
      </tr>`;
    })
    .join("");
}

/* --- modal --------------------------------------------------------------- */

function openModal(apiName) {
  const a = state.metrics?.apis?.[apiName];
  if (!a) return;
  $("modal-title").textContent = apiName;

  const statusRows = Object.entries(a.responses || {})
    .sort((x, y) => y[1] - x[1])
    .map(([code, n]) => `<dt>HTTP ${escapeHtml(code)}</dt><dd>${fmt.number(n)}</dd>`)
    .join("");
  const keyRows = Object.entries(a.key_usage || {})
    .sort((x, y) => y[1] - x[1])
    .map(
      ([key, n]) =>
        `<dt class="mono">${escapeHtml(key)}</dt><dd>${fmt.number(n)}</dd>`
    )
    .join("");

  $("modal-body").innerHTML = `
    <dl class="kv">
      <dt>Total requests</dt><dd>${fmt.number(a.requests)}</dd>
      <dt>Errors</dt><dd>${fmt.number(a.errors)}</dd>
      <dt>Active requests</dt><dd>${fmt.number(a.active_requests)}</dd>
      <dt>Avg latency</dt><dd>${fmt.latency(a.avg_response_time_ms)}</dd>
      <dt>Rate-limit hits</dt><dd>${fmt.number(a.rate_limit_hits)}</dd>
      <dt>Queue hits</dt><dd>${fmt.number(a.queue_hits)}</dd>
      <dt>Last request</dt><dd>${fmt.ago(a.last_request_time)}</dd>
    </dl>
    ${statusRows ? `<div class="stat-label" style="margin:18px 0 8px">Status codes</div><dl class="kv">${statusRows}</dl>` : ""}
    ${keyRows ? `<div class="stat-label" style="margin:18px 0 8px">Key usage</div><dl class="kv">${keyRows}</dl>` : ""}
  `;
  $("modal").hidden = false;
}

function closeModal() {
  $("modal").hidden = true;
}

/* --- refresh loop -------------------------------------------------------- */

async function refresh() {
  try {
    const [metrics, history, queue] = await Promise.all([
      getJSON("/metrics"),
      getJSON("/history"),
      getJSON("/queue"),
    ]);
    state.metrics = metrics;
    state.history = history.history || [];
    state.queues = queue.queue_sizes || {};

    renderStats(metrics.global);
    renderApiTable(metrics.apis);
    renderDistributions(metrics.apis);
    renderQueues(state.queues);
    renderHistory(state.history);

    $("last-updated").textContent =
      "updated " + new Date().toLocaleTimeString("en-US", { hour12: false });
  } catch (err) {
    console.error(err);
    toast("Failed to refresh dashboard data", "error");
  }
}

/* --- control actions ----------------------------------------------------- */

async function resetMetrics() {
  if (!confirm("Reset all metrics? This cannot be undone.")) return;
  try {
    await postJSON("/metrics/reset");
    toast("Metrics reset");
    refresh();
  } catch {
    toast("Failed to reset metrics", "error");
  }
}

async function clearAllQueues() {
  if (!confirm("Clear all queued requests?")) return;
  try {
    const res = await postJSON("/queue/clear");
    toast(`Cleared ${res.cleared_count ?? 0} queued requests`);
    refresh();
  } catch {
    toast("Failed to clear queues", "error");
  }
}

/* --- theme --------------------------------------------------------------- */

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("nyaproxy-theme", theme);
  const dark = theme === "dark";
  document.querySelector(".icon-moon").style.display = dark ? "" : "none";
  document.querySelector(".icon-sun").style.display = dark ? "none" : "";
}

/* --- init ---------------------------------------------------------------- */

function init() {
  applyTheme(localStorage.getItem("nyaproxy-theme") || "dark");

  $("theme-toggle").addEventListener("click", () => {
    const next =
      document.documentElement.getAttribute("data-theme") === "dark"
        ? "light"
        : "dark";
    applyTheme(next);
  });

  $("refresh-btn").addEventListener("click", refresh);
  $("reset-metrics-btn").addEventListener("click", resetMetrics);
  $("clear-all-queues-btn").addEventListener("click", clearAllQueues);
  $("modal-close").addEventListener("click", closeModal);
  $("modal").addEventListener("click", (e) => {
    if (e.target.id === "modal") closeModal();
  });

  $("api-search").addEventListener("input", (e) => {
    state.apiFilter = e.target.value.trim().toLowerCase();
    if (state.metrics) renderApiTable(state.metrics.apis);
  });
  $("history-search").addEventListener("input", (e) => {
    state.historyFilter = e.target.value.trim().toLowerCase();
    renderHistory(state.history);
  });

  refresh();
  setInterval(refresh, REFRESH_MS);
}

document.addEventListener("DOMContentLoaded", init);
