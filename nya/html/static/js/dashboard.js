// NyaProxy Dashboard - Frontend JavaScript
// Handles data fetching, visualization, and interactivity for the dashboard

const baseUrl = new URL(".", window.location).href;
const apiUrl = `${baseUrl}api`;

const metricsUrl = `${apiUrl}/metrics`;
const historyUrl = `${apiUrl}/history`;
const queueUrl = `${apiUrl}/queue`;
const analyticsUrl = `${apiUrl}/analytics`;

// Configuration
const CONFIG = {
  refreshInterval: 30000, // Auto-refresh interval in milliseconds
  chartColors: {
    blue: {
      primary: "#3b82f6",
      light: "rgba(59, 130, 246, 0.1)",
      dark: "#2563eb",
    },
    red: {
      primary: "#ef4444",
      light: "rgba(239, 68, 68, 0.1)",
      dark: "#dc2626",
    },
    green: {
      primary: "#10b981",
      light: "rgba(16, 185, 129, 0.1)",
      dark: "#059669",
    },
    yellow: {
      primary: "#f59e0b",
      light: "rgba(245, 158, 11, 0.1)",
      dark: "#d97706",
    },
    pink: {
      primary: "#ec4899",
      light: "rgba(236, 72, 153, 0.1)",
      dark: "#db2777",
    },
    purple: {
      primary: "#8b5cf6",
      light: "rgba(139, 92, 246, 0.1)",
      dark: "#7c3aed",
    },
  },
  maxItemsInCharts: 10,
  statusCodeColors: {
    200: "#10b981",
    201: "#059669",
    204: "#34d399",
    400: "#f59e0b",
    401: "#f97316",
    403: "#fb923c",
    404: "#fbbf24",
    429: "#fb7185",
    500: "#ef4444",
    502: "#dc2626",
    503: "#b91c1c",
    504: "#991b1b",
  },
};

// State management
const state = {
  metrics: null,
  history: [],
  queueStatus: {},
  analytics: null,
  filters: {
    apiName: "all",
    keyId: "all",
    timeRange: "24h",
  },
  charts: {},
  lastUpdated: null,
  refreshTimer: null,
};

// DOM Elements cache
const elements = {};

// Utility functions
const utils = {
  formatNumber(num) {
    if (num === undefined || num === null) return "0";
    if (num === 0) return "0";

    if (num >= 1000000) {
      return (num / 1000000).toFixed(1) + "M";
    } else if (num >= 1000) {
      return (num / 1000).toFixed(1) + "K";
    }
    return num.toString();
  },

  formatTime(timestamp) {
    if (!timestamp) return "N/A";
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  },

  formatDate(timestamp) {
    if (!timestamp) return "N/A";
    const date = new Date(timestamp * 1000);
    return (
      date.toLocaleDateString() +
      " " +
      date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    );
  },

  formatTimeAgo(timestamp) {
    if (!timestamp) return "N/A";

    const seconds = Math.floor(Date.now() / 1000 - timestamp);

    if (seconds < 60) {
      return `${seconds}s ago`;
    } else if (seconds < 3600) {
      return `${Math.floor(seconds / 60)}m ago`;
    } else if (seconds < 86400) {
      return `${Math.floor(seconds / 3600)}h ago`;
    } else {
      return `${Math.floor(seconds / 86400)}d ago`;
    }
  },

  formatDuration(seconds) {
    if (!seconds) return "0s";

    if (seconds < 60) {
      return `${Math.floor(seconds)}s`;
    } else if (seconds < 3600) {
      const minutes = Math.floor(seconds / 60);
      const secs = Math.floor(seconds % 60);
      return `${minutes}m ${secs}s`;
    } else if (seconds < 86400) {
      const hours = Math.floor(seconds / 3600);
      const minutes = Math.floor((seconds % 3600) / 60);
      return `${hours}h ${minutes}m`;
    } else {
      const days = Math.floor(seconds / 86400);
      const hours = Math.floor((seconds % 86400) / 3600);
      return `${days}d ${hours}h`;
    }
  },

  formatResponseTime(ms) {
    if (ms === undefined || ms === null) return "N/A";
    if (ms === 0) return "0ms";

    // Format with proper precision
    if (ms < 1) {
      return "<1ms";
    } else if (ms < 1000) {
      return `${Math.round(ms)}ms`;
    } else {
      return `${(ms / 1000).toFixed(2)}s`;
    }
  },

  getStatusCodeClass(code) {
    if (code >= 200 && code < 300) {
      return "bg-green-500";
    } else if (code >= 400 && code < 500) {
      return "bg-yellow-500";
    } else if (code >= 500) {
      return "bg-red-500";
    } else {
      return "bg-blue-500";
    }
  },

  getStatusCodeColor(code) {
    code = code.toString();
    if (CONFIG.statusCodeColors[code]) {
      return CONFIG.statusCodeColors[code];
    }

    // Default colors based on ranges
    if (code.startsWith("2")) {
      return CONFIG.statusCodeColors["200"];
    } else if (code.startsWith("4")) {
      return CONFIG.statusCodeColors["400"];
    } else if (code.startsWith("5")) {
      return CONFIG.statusCodeColors["500"];
    }

    return "#64748b"; // Default gray
  },

  // Truncate text with ellipsis
  truncate(text, length = 20) {
    if (!text) return "";
    return text.length > length ? text.substring(0, length) + "..." : text;
  },

  // Generate a random color with good contrast
  randomColor(index) {
    const colors = Object.values(CONFIG.chartColors).map((c) => c.primary);
    return colors[index % colors.length];
  },

  showToast(message, type = "success") {
    const toast = document.getElementById("toast");
    const toastMessage = document.getElementById("toast-message");
    const toastIcon = document.getElementById("toast-icon");

    toastMessage.textContent = message;

    // Set icon and color based on type
    if (type === "success") {
      toastIcon.innerHTML =
        '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" /></svg>';
      toastIcon.className = "mr-3 text-green-500";
    } else if (type === "error") {
      toastIcon.innerHTML =
        '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" /></svg>';
      toastIcon.className = "mr-3 text-red-500";
    } else if (type === "warning") {
      toastIcon.innerHTML =
        '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" /></svg>';
      toastIcon.className = "mr-3 text-yellow-500";
    }

    // Show the toast
    toast.classList.remove("toast-hidden", "translate-y-full", "opacity-0");
    toast.classList.add("toast-visible");

    // Hide the toast after 3 seconds
    setTimeout(() => {
      toast.classList.remove("toast-visible");
      toast.classList.add("toast-hidden", "translate-y-full", "opacity-0");
    }, 3000);
  },
};

// API service for handling data fetching
const apiService = {
  async fetchMetrics() {
    try {
      const response = await fetch(metricsUrl);
      if (!response.ok) throw new Error("Failed to fetch metrics");

      const data = await response.json();
      state.metrics = data;
      state.lastUpdated = new Date();
      return data;
    } catch (error) {
      console.error("Error fetching metrics:", error);
      utils.showToast("Failed to fetch metrics data", "error");
      throw error;
    }
  },

  async fetchHistory() {
    try {
      const response = await fetch(historyUrl);
      if (!response.ok) throw new Error("Failed to fetch history");

      const data = await response.json();
      state.history = data.history || [];
      return data.history;
    } catch (error) {
      console.error("Error fetching history:", error);
      utils.showToast("Failed to fetch request history", "error");
      throw error;
    }
  },

  async fetchQueueStatus() {
    try {
      const response = await fetch(queueUrl);
      if (!response.ok) throw new Error("Failed to fetch queue status");

      const data = await response.json();
      state.queueStatus = data;
      return data;
    } catch (error) {
      console.error("Error fetching queue status:", error);
      return null;
    }
  },

  async fetchAnalytics(apiName = null, keyId = null, timeRange = "24h") {
    let url = `${analyticsUrl}?time_range=${timeRange}`;
    if (apiName && apiName !== "all") url += `&api_name=${apiName}`;
    if (keyId && keyId !== "all") url += `&key_id=${keyId}`;

    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error("Failed to fetch analytics");

      const data = await response.json();
      state.analytics = data;
      return data;
    } catch (error) {
      console.error("Error fetching analytics:", error);
      utils.showToast("Failed to fetch analytics data", "error");
      throw error;
    }
  },

  async resetMetrics() {
    try {
      const response = await fetch(`${metricsUrl}/reset`, {
        method: "POST",
      });
      if (!response.ok) throw new Error("Failed to reset metrics");

      const data = await response.json();
      utils.showToast("Metrics reset successfully");
      return data;
    } catch (error) {
      console.error("Error resetting metrics:", error);
      utils.showToast("Failed to reset metrics", "error");
      throw error;
    }
  },

  async clearAllQueues() {
    try {
      const response = await fetch(`${queueUrl}/clear`, {
        method: "POST",
      });
      if (!response.ok) throw new Error("Failed to clear queues");

      const data = await response.json();
      utils.showToast(`Cleared ${data.cleared_count} queued requests`);
      return data;
    } catch (error) {
      console.error("Error clearing queues:", error);
      utils.showToast("Failed to clear queues", "error");
      throw error;
    }
  },

  async clearQueue(apiName) {
    try {
      const response = await fetch(`${queueUrl}/clear/${apiName}`, {
        method: "POST",
      });
      if (!response.ok) throw new Error("Failed to clear queue");

      const data = await response.json();
      utils.showToast(
        `Cleared ${data.cleared_count} queued requests for ${apiName}`
      );
      return data;
    } catch (error) {
      console.error(`Error clearing queue for ${apiName}:`, error);
      utils.showToast(`Failed to clear queue for ${apiName}`, "error");
      throw error;
    }
  },
};

// UI rendering functions
const ui = {
  // Initialize and cache DOM elements
  cacheElements() {
    // Global stats elements
    elements.totalRequests = document.getElementById("total-requests");
    elements.totalErrors = document.getElementById("total-errors");
    elements.totalRateLimits = document.getElementById("total-rate-limits");
    elements.uptime = document.getElementById("uptime");
    elements.totalRequestsBar = document.getElementById("total-requests-bar");
    elements.totalErrorsBar = document.getElementById("total-errors-bar");
    elements.totalRateLimitsBar = document.getElementById(
      "total-rate-limits-bar"
    );

    // Filter elements
    elements.apiFilter = document.getElementById("api-filter");
    elements.keyFilter = document.getElementById("key-filter");
    elements.timeRange = document.getElementById("time-range");
    elements.filterSummary = document.getElementById("filter-summary");

    // Table elements
    elements.apiTableBody = document.getElementById("api-table-body");
    elements.apiCardsContainer = document.getElementById("api-cards-container");
    elements.historyTableBody = document.getElementById("history-table-body");
    elements.historyCardsContainer = document.getElementById(
      "history-cards-container"
    );

    // Queue elements
    elements.queueContainer = document.getElementById("queue-container");

    // Chart canvases
    elements.trafficChart = document.getElementById("traffic-chart");
    elements.responseTimeChart = document.getElementById("response-time-chart");
    elements.statusCodeChart = document.getElementById("status-code-chart");
    elements.apiDistributionChart = document.getElementById(
      "api-distribution-chart"
    );
    elements.keyUsageChart = document.getElementById("key-usage-chart");

    // Action buttons
    elements.refreshButton = document.getElementById("refresh-button");
    elements.resetMetricsBtn = document.getElementById("reset-metrics-btn");
    elements.clearAllQueuesBtn = document.getElementById(
      "clear-all-queues-btn"
    );
    elements.themeToggle = document.getElementById("theme-toggle");

    // Search inputs
    elements.apiSearch = document.getElementById("api-search");
    elements.historySearch = document.getElementById("history-search");

    // Modal elements
    elements.apiDetailsModal = document.getElementById("api-details-modal");
    elements.modalTitle = document.getElementById("modal-title");
    elements.modalContent = document.getElementById("modal-content");
    elements.closeModal = document.getElementById("close-modal");

    // Last updated indicator
    elements.lastUpdated = document.getElementById("last-updated");
  },

  // Update global statistics display
  updateGlobalStats() {
    if (!state.metrics || !state.metrics.global) return;

    const global = state.metrics.global;

    // Update counters with formatted numbers
    elements.totalRequests.textContent = utils.formatNumber(
      global.total_requests
    );
    elements.totalErrors.textContent = utils.formatNumber(global.total_errors);
    elements.totalRateLimits.textContent = utils.formatNumber(
      global.total_rate_limit_hits
    );
    elements.uptime.textContent = utils.formatDuration(global.uptime_seconds);

    // Update progress bars
    // Calculate percentages for visualization
    const maxRequests = Math.max(global.total_requests, 1);
    const errorPercentage = (global.total_errors / maxRequests) * 100;
    const rateLimitPercentage =
      (global.total_rate_limit_hits / maxRequests) * 100;

    elements.totalRequestsBar.style.width = "100%";
    elements.totalErrorsBar.style.width = `${Math.min(errorPercentage, 100)}%`;
    elements.totalRateLimitsBar.style.width = `${Math.min(
      rateLimitPercentage,
      100
    )}%`;

    // Update last updated text
    if (state.lastUpdated) {
      elements.lastUpdated.textContent = `Last updated: ${state.lastUpdated.toLocaleTimeString()}`;
    }
  },

  // Render API table
  renderApiTable() {
    if (!state.metrics || !state.metrics.apis) return;

    const apis = state.metrics.apis;
    const searchTerm = elements.apiSearch.value.toLowerCase();

    // Clear existing content
    elements.apiTableBody.innerHTML = "";
    elements.apiCardsContainer.innerHTML = "";

    // Check if we have APIs to display
    if (Object.keys(apis).length === 0) {
      const emptyRow = document.createElement("tr");
      emptyRow.innerHTML = `
        <td colspan="6" class="px-6 py-4 text-center text-sm text-slate-500 dark:text-slate-400">
          No APIs have been used yet
        </td>
      `;
      elements.apiTableBody.appendChild(emptyRow);
      return;
    }

    // Sort APIs by request count (descending)
    const sortedApis = Object.entries(apis).sort(
      (a, b) => b[1].requests - a[1].requests
    );

    // Filter APIs by search term
    const filteredApis = sortedApis.filter(([apiName]) =>
      apiName.toLowerCase().includes(searchTerm)
    );

    if (filteredApis.length === 0) {
      const emptyRow = document.createElement("tr");
      emptyRow.innerHTML = `
        <td colspan="6" class="px-6 py-4 text-center text-sm text-slate-500 dark:text-slate-400">
          No APIs match your search
        </td>
      `;
      elements.apiTableBody.appendChild(emptyRow);
      return;
    }

    // Render each API row
    filteredApis.forEach(([apiName, apiData]) => {
      // Desktop view (table row)
      const row = document.createElement("tr");
      row.className =
        "hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors duration-150 clickable-row";
      row.onclick = () => ui.showApiDetails(apiName, apiData);

      const lastRequestTime = apiData.last_request_time
        ? utils.formatTimeAgo(apiData.last_request_time)
        : "Never";

      row.innerHTML = `
        <td class="px-6 py-4 whitespace-nowrap">
          <div class="font-medium">${apiName}</div>
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-sm">
          ${utils.formatNumber(apiData.requests)}
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-sm">
          <span class="px-2 py-1 rounded-full text-xs ${
            apiData.errors > 0
              ? "bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300"
              : "bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300"
          }">
            ${utils.formatNumber(apiData.errors)}
          </span>
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-sm">
          ${utils.formatResponseTime(apiData.avg_response_time_ms)}
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-sm text-slate-500 dark:text-slate-400">
          ${lastRequestTime}
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-right text-sm">
          <button class="view-details-btn text-pink-500 hover:text-pink-700 dark:hover:text-pink-400 font-medium">
            View Details
          </button>
        </td>
      `;

      elements.apiTableBody.appendChild(row);

      // Mobile view (card)
      const card = document.createElement("div");
      card.className = "responsive-table-card modern-card";
      card.onclick = () => ui.showApiDetails(apiName, apiData);

      card.innerHTML = `
        <div class="responsive-table-card-header">
          <div>${apiName}</div>
          <div class="px-2 py-1 rounded-full text-xs ${
            apiData.errors > 0
              ? "bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300"
              : "bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300"
          }">
            ${utils.formatNumber(apiData.errors)} errors
          </div>
        </div>
        <div class="responsive-table-card-content">
          <div>
            <div class="responsive-table-card-label">Requests</div>
            <div>${utils.formatNumber(apiData.requests)}</div>
          </div>
          <div>
            <div class="responsive-table-card-label">Avg Response</div>
            <div>${utils.formatResponseTime(apiData.avg_response_time_ms)}</div>
          </div>
          <div>
            <div class="responsive-table-card-label">Last Request</div>
            <div>${lastRequestTime}</div>
          </div>
          <div>
            <div class="responsive-table-card-label">Rate Limits</div>
            <div>${utils.formatNumber(apiData.rate_limit_hits || 0)}</div>
          </div>
        </div>
      `;

      elements.apiCardsContainer.appendChild(card);
    });
  },

  // Render history table
  renderHistoryTable() {
    if (!state.history) return;

    const history = state.history;
    const searchTerm = elements.historySearch
      ? elements.historySearch.value.toLowerCase()
      : "";

    // Clear existing content
    elements.historyTableBody.innerHTML = "";
    elements.historyCardsContainer.innerHTML = "";

    // Check if we have history to display
    if (history.length === 0) {
      const emptyRow = document.createElement("tr");
      emptyRow.innerHTML = `
        <td colspan="5" class="px-6 py-4 text-center text-sm text-slate-500 dark:text-slate-400">
          No request history available
        </td>
      `;
      elements.historyTableBody.appendChild(emptyRow);
      return;
    }

    // Only show response entries for the table (they have status_code)
    const responseEntries = history.filter(
      (entry) =>
        entry.type === "response" &&
        (searchTerm === "" ||
          entry.api_name.toLowerCase().includes(searchTerm) ||
          entry.key_id.toLowerCase().includes(searchTerm) ||
          (entry.status_code &&
            entry.status_code.toString().includes(searchTerm)))
    );

    // Limit to most recent 50 entries
    const limitedEntries = responseEntries.slice(-50);

    if (limitedEntries.length === 0) {
      const emptyRow = document.createElement("tr");
      emptyRow.innerHTML = `
        <td colspan="5" class="px-6 py-4 text-center text-sm text-slate-500 dark:text-slate-400">
          No matching request history found
        </td>
      `;
      elements.historyTableBody.appendChild(emptyRow);
      return;
    }

    // Render each history row
    limitedEntries.forEach((entry) => {
      // Desktop view (table row)
      const row = document.createElement("tr");
      row.className =
        "hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors duration-150";

      const statusColorClass = utils.getStatusCodeClass(entry.status_code);

      row.innerHTML = `
        <td class="px-6 py-4 whitespace-nowrap text-sm text-slate-500 dark:text-slate-400">
          ${utils.formatTime(entry.timestamp)}
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-sm">
          ${entry.api_name}
        </td>
        <td class="px-6 py-4 whitespace-nowrap">
          <span class="inline-flex items-center justify-center w-12 h-6 rounded-full text-xs text-white font-medium ${statusColorClass}">
            ${entry.status_code}
          </span>
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-sm">
          ${
            entry.elapsed_ms
              ? utils.formatResponseTime(entry.elapsed_ms)
              : "N/A"
          }
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-sm text-slate-500 dark:text-slate-400">
          ${utils.truncate(entry.key_id, 24)}
        </td>
      `;

      elements.historyTableBody.appendChild(row);

      // Mobile view (card)
      const card = document.createElement("div");
      card.className = "responsive-table-card modern-card";

      card.innerHTML = `
        <div class="responsive-table-card-header">
          <div>${entry.api_name}</div>
          <div class="inline-flex items-center justify-center w-12 h-6 rounded-full text-xs text-white font-medium ${statusColorClass}">
            ${entry.status_code}
          </div>
        </div>
        <div class="responsive-table-card-content">
          <div>
            <div class="responsive-table-card-label">Time</div>
            <div>${utils.formatTime(entry.timestamp)}</div>
          </div>
          <div>
            <div class="responsive-table-card-label">Response</div>
            <div>${
              entry.elapsed_ms
                ? utils.formatResponseTime(entry.elapsed_ms)
                : "N/A"
            }</div>
          </div>
          <div>
            <div class="responsive-table-card-label">Key</div>
            <div class="truncate max-w-[120px]">${utils.truncate(
              entry.key_id,
              16
            )}</div>
          </div>
        </div>
      `;

      elements.historyCardsContainer.appendChild(card);
    });
  },

  // Render queue status
  renderQueueStatus() {
    if (!state.queueStatus || !state.queueStatus.queue_sizes) return;

    const queueSizes = state.queueStatus.queue_sizes;

    // Clear existing content
    elements.queueContainer.innerHTML = "";

    // Check if we have queues to display
    if (Object.keys(queueSizes).length === 0) {
      const emptyCard = document.createElement("div");
      emptyCard.className = "modern-card p-5 col-span-full";
      emptyCard.innerHTML = `
        <div class="empty-state">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 mx-auto text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 6h16M4 12h16M4 18h7" />
          </svg>
          <p>No active request queues</p>
        </div>
      `;
      elements.queueContainer.appendChild(emptyCard);
      return;
    }

    // Render each queue
    Object.entries(queueSizes).forEach(([apiName, queueSize]) => {
      const card = document.createElement("div");
      card.className = "modern-card p-5";

      // Determine status color
      let statusClass = "text-green-500";
      let statusText = "Normal";

      if (queueSize > 50) {
        statusClass = "text-red-500";
        statusText = "Heavy Load";
      } else if (queueSize > 10) {
        statusClass = "text-yellow-500";
        statusText = "Moderate Load";
      }

      card.innerHTML = `
        <div class="flex justify-between items-start mb-2">
          <h3 class="font-medium">${apiName}</h3>
          <span class="badge bg-slate-100 dark:bg-slate-700 text-slate-800 dark:text-slate-200 text-xs">Queue</span>
        </div>
        <div class="text-2xl font-bold mb-2">${queueSize}</div>
        <div class="flex justify-between items-center">
          <span class="text-sm ${statusClass}">${statusText}</span>
          <button class="clear-queue-btn text-xs px-2 py-1 bg-yellow-100 dark:bg-yellow-900/30 text-yellow-800 dark:text-yellow-300 rounded hover:bg-yellow-200 dark:hover:bg-yellow-800/50 transition-colors"
                  data-api="${apiName}">
            Clear Queue
          </button>
        </div>
      `;

      // Add event listener to clear queue button
      card.querySelector(".clear-queue-btn").addEventListener("click", (e) => {
        e.stopPropagation(); // Prevent card click
        const apiName = e.target.getAttribute("data-api");
        apiService.clearQueue(apiName).then(() => {
          refreshData();
        });
      });

      elements.queueContainer.appendChild(card);
    });
  },

  // Update filter dropdowns
  updateFilterDropdowns() {
    if (!state.metrics || !state.metrics.apis) return;

    const apis = Object.keys(state.metrics.apis);

    // Reset options first
    elements.apiFilter.innerHTML = '<option value="all">All APIs</option>';
    elements.keyFilter.innerHTML = '<option value="all">All Keys</option>';

    // Add API options
    apis.forEach((apiName) => {
      const option = document.createElement("option");
      option.value = apiName;
      option.textContent = apiName;
      elements.apiFilter.appendChild(option);
    });

    // When an API is selected, update the key filter
    if (
      state.filters.apiName !== "all" &&
      state.metrics.apis[state.filters.apiName]
    ) {
      const apiData = state.metrics.apis[state.filters.apiName];
      const keys = apiData.key_usage ? Object.keys(apiData.key_usage) : [];

      keys.forEach((keyId) => {
        const option = document.createElement("option");
        option.value = keyId;
        option.textContent = utils.truncate(keyId, 24);
        elements.keyFilter.appendChild(option);
      });
    } else {
      // Collect all keys across all APIs
      const allKeys = new Set();

      Object.values(state.metrics.apis).forEach((apiData) => {
        if (apiData.key_usage) {
          Object.keys(apiData.key_usage).forEach((key) => allKeys.add(key));
        }
      });

      // Add all unique keys to the dropdown
      Array.from(allKeys)
        .sort()
        .forEach((keyId) => {
          const option = document.createElement("option");
          option.value = keyId;
          option.textContent = utils.truncate(keyId, 24);
          elements.keyFilter.appendChild(option);
        });
    }

    // Set selected values based on current filters
    elements.apiFilter.value = state.filters.apiName;
    elements.keyFilter.value = state.filters.keyId;
    elements.timeRange.value = state.filters.timeRange;

    // Update filter summary text
    let summaryText = "Showing data for ";

    if (state.filters.apiName === "all") {
      summaryText += "all APIs";
    } else {
      summaryText += `API "${state.filters.apiName}"`;
    }

    if (state.filters.keyId !== "all") {
      summaryText += ` with key "${utils.truncate(state.filters.keyId, 16)}"`;
    }

    let timeRangeText = "";
    switch (state.filters.timeRange) {
      case "1h":
        timeRangeText = "the last hour";
        break;
      case "24h":
        timeRangeText = "the last 24h";
        break;
      case "7d":
        timeRangeText = "the last 7 days";
        break;
      case "30d":
        timeRangeText = "the last 30 days";
        break;
      case "all":
        timeRangeText = "all time";
        break;
    }

    summaryText += ` over ${timeRangeText}`;
    elements.filterSummary.textContent = summaryText;
  },

  // Show API details modal
  showApiDetails(apiName, apiData) {
    elements.modalTitle.textContent = `API: ${apiName}`;

    // Format status code distribution
    const statusCodes = apiData.responses || {};
    const statusCodeHtml =
      Object.entries(statusCodes).length > 0
        ? Object.entries(statusCodes)
            .sort(([a], [b]) => parseInt(a) - parseInt(b))
            .map(([code, count]) => {
              const colorClass = utils.getStatusCodeClass(code);
              return `
              <div class="flex items-center justify-between mb-2">
                <div class="flex items-center">
                  <span class="inline-flex items-center justify-center w-10 h-6 rounded-full text-xs text-white font-medium ${colorClass} mr-2">
                    ${code}
                  </span>
                  <span class="text-sm">${count} requests</span>
                </div>
                <span class="text-xs text-slate-500 dark:text-slate-400">
                  ${((count / apiData.requests) * 100).toFixed(1)}%
                </span>
              </div>
            `;
            })
            .join("")
        : '<div class="text-sm text-slate-500 dark:text-slate-400">No status code data available</div>';

    // Format key usage
    const keyUsage = apiData.key_usage || {};
    const keyUsageHtml =
      Object.entries(keyUsage).length > 0
        ? Object.entries(keyUsage)
            .sort(([, a], [, b]) => b - a)
            .map(([keyId, count]) => {
              return `
              <div class="flex items-center justify-between mb-2">
                <div class="truncate max-w-[200px] text-sm">${keyId}</div>
                <span class="badge bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300 text-xs">
                  ${count} requests
                </span>
              </div>
            `;
            })
            .join("")
        : '<div class="text-sm text-slate-500 dark:text-slate-400">No key usage data available</div>';

    // Build modal content
    elements.modalContent.innerHTML = `
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div class="bg-slate-50 dark:bg-slate-800 p-4 rounded-lg">
          <h4 class="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">Total Requests</h4>
          <p class="text-2xl font-bold">${utils.formatNumber(
            apiData.requests
          )}</p>
        </div>
        <div class="bg-slate-50 dark:bg-slate-800 p-4 rounded-lg">
          <h4 class="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">Error Rate</h4>
          <p class="text-2xl font-bold">${
            apiData.errors > 0
              ? ((apiData.errors / apiData.requests) * 100).toFixed(1) + "%"
              : "0%"
          }</p>
        </div>
        <div class="bg-slate-50 dark:bg-slate-800 p-4 rounded-lg">
          <h4 class="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">Avg Response Time</h4>
          <p class="text-2xl font-bold">${utils.formatResponseTime(
            apiData.avg_response_time_ms
          )}</p>
          <div class="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Min: ${utils.formatResponseTime(apiData.min_response_time_ms)} / 
            Max: ${utils.formatResponseTime(apiData.max_response_time_ms)}
          </div>
        </div>
        <div class="bg-slate-50 dark:bg-slate-800 p-4 rounded-lg">
          <h4 class="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">Queue & Rate Limits</h4>
          <p class="text-2xl font-bold">${utils.formatNumber(
            apiData.queue_hits
          )}</p>
          <div class="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Rate Limit Hits: ${utils.formatNumber(apiData.rate_limit_hits)}
          </div>
        </div>
      </div>
      
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <h4 class="font-medium mb-3">Status Code Distribution</h4>
          <div class="bg-slate-50 dark:bg-slate-800 p-4 rounded-lg">
            ${statusCodeHtml}
          </div>
        </div>
        <div>
          <h4 class="font-medium mb-3">API Key Usage</h4>
          <div class="bg-slate-50 dark:bg-slate-800 p-4 rounded-lg max-h-[200px] overflow-y-auto">
            ${keyUsageHtml}
          </div>
        </div>
      </div>
    `;

    // Show the modal
    elements.apiDetailsModal.classList.remove("hidden");
  },

  // Hide API details modal
  hideApiDetails() {
    elements.apiDetailsModal.classList.add("hidden");
  },

  // Initialize and render all charts
  initCharts() {
    // Define common chart options
    const commonOptions = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: {
            color: document.documentElement.classList.contains("dark")
              ? "#e2e8f0"
              : "#1e293b",
            font: {
              family:
                "'Nunito', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
            },
          },
        },
        tooltip: {
          backgroundColor: document.documentElement.classList.contains("dark")
            ? "rgba(15, 23, 42, 0.95)"
            : "rgba(255, 255, 255, 0.95)",
          titleColor: document.documentElement.classList.contains("dark")
            ? "#e2e8f0"
            : "#1e293b",
          bodyColor: document.documentElement.classList.contains("dark")
            ? "#cbd5e1"
            : "#475569",
          borderColor: document.documentElement.classList.contains("dark")
            ? "rgba(30, 41, 59, 0.5)"
            : "rgba(226, 232, 240, 0.5)",
          borderWidth: 1,
          padding: 10,
          boxPadding: 6,
          usePointStyle: true,
          bodyFont: {
            family:
              "'Nunito', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
          },
          titleFont: {
            family:
              "'Nunito', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
            weight: 600,
          },
          cornerRadius: 8,
          displayColors: true,
          boxWidth: 8,
          boxHeight: 8,
        },
      },
    };

    // Traffic chart (requests and errors over time)
    state.charts.traffic = new Chart(elements.trafficChart, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Requests",
            data: [],
            borderColor: CONFIG.chartColors.blue.primary,
            backgroundColor: CONFIG.chartColors.blue.light,
            fill: true,
            tension: 0.3,
            borderWidth: 2,
            pointRadius: 3,
            pointHoverRadius: 5,
          },
          {
            label: "Errors",
            data: [],
            borderColor: CONFIG.chartColors.red.primary,
            backgroundColor: CONFIG.chartColors.red.light,
            fill: true,
            tension: 0.3,
            borderWidth: 2,
            pointRadius: 3,
            pointHoverRadius: 5,
          },
        ],
      },
      options: {
        ...commonOptions,
        scales: {
          x: {
            ticks: {
              color: document.documentElement.classList.contains("dark")
                ? "#cbd5e1"
                : "#475569",
              font: {
                family:
                  "'Nunito', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
              },
            },
            grid: {
              color: document.documentElement.classList.contains("dark")
                ? "rgba(71, 85, 105, 0.2)"
                : "rgba(203, 213, 225, 0.5)",
            },
          },
          y: {
            beginAtZero: true,
            ticks: {
              color: document.documentElement.classList.contains("dark")
                ? "#cbd5e1"
                : "#475569",
              font: {
                family:
                  "'Nunito', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
              },
            },
            grid: {
              color: document.documentElement.classList.contains("dark")
                ? "rgba(71, 85, 105, 0.2)"
                : "rgba(203, 213, 225, 0.5)",
            },
          },
        },
      },
    });

    // Response time chart
    state.charts.responseTime = new Chart(elements.responseTimeChart, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Avg Response Time (ms)",
            data: [],
            borderColor: CONFIG.chartColors.green.primary,
            backgroundColor: CONFIG.chartColors.green.light,
            fill: true,
            tension: 0.3,
            borderWidth: 2,
            pointRadius: 3,
            pointHoverRadius: 5,
          },
        ],
      },
      options: {
        ...commonOptions,
        scales: {
          x: {
            ticks: {
              color: document.documentElement.classList.contains("dark")
                ? "#cbd5e1"
                : "#475569",
              font: {
                family:
                  "'Nunito', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
              },
            },
            grid: {
              color: document.documentElement.classList.contains("dark")
                ? "rgba(71, 85, 105, 0.2)"
                : "rgba(203, 213, 225, 0.5)",
            },
          },
          y: {
            beginAtZero: true,
            ticks: {
              color: document.documentElement.classList.contains("dark")
                ? "#cbd5e1"
                : "#475569",
              font: {
                family:
                  "'Nunito', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
              },
              callback: function (value) {
                return value + "ms";
              },
            },
            grid: {
              color: document.documentElement.classList.contains("dark")
                ? "rgba(71, 85, 105, 0.2)"
                : "rgba(203, 213, 225, 0.5)",
            },
          },
        },
      },
    });

    // Status code distribution chart
    state.charts.statusCode = new Chart(elements.statusCodeChart, {
      type: "doughnut",
      data: {
        labels: [],
        datasets: [
          {
            data: [],
            backgroundColor: [],
            borderColor: document.documentElement.classList.contains("dark")
              ? "rgba(15, 23, 42, 1)"
              : "white",
            borderWidth: 2,
            hoverOffset: 5,
          },
        ],
      },
      options: {
        ...commonOptions,
        cutout: "65%",
        plugins: {
          ...commonOptions.plugins,
          legend: {
            position: "right",
            labels: {
              color: document.documentElement.classList.contains("dark")
                ? "#e2e8f0"
                : "#1e293b",
              font: {
                family:
                  "'Nunito', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
                size: 11,
              },
              boxWidth: 12,
              padding: 10,
            },
          },
        },
      },
    });

    // API distribution chart
    state.charts.apiDistribution = new Chart(elements.apiDistributionChart, {
      type: "bar",
      data: {
        labels: [],
        datasets: [
          {
            label: "API Requests",
            data: [],
            backgroundColor: [],
            borderColor: document.documentElement.classList.contains("dark")
              ? "rgba(15, 23, 42, 1)"
              : "white",
            borderWidth: 1,
            borderRadius: 5,
          },
        ],
      },
      options: {
        ...commonOptions,
        scales: {
          x: {
            ticks: {
              color: document.documentElement.classList.contains("dark")
                ? "#cbd5e1"
                : "#475569",
              font: {
                family:
                  "'Nunito', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
              },
            },
            grid: {
              display: false,
            },
          },
          y: {
            beginAtZero: true,
            ticks: {
              color: document.documentElement.classList.contains("dark")
                ? "#cbd5e1"
                : "#475569",
              font: {
                family:
                  "'Nunito', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
              },
            },
            grid: {
              color: document.documentElement.classList.contains("dark")
                ? "rgba(71, 85, 105, 0.2)"
                : "rgba(203, 213, 225, 0.5)",
            },
          },
        },
        plugins: {
          ...commonOptions.plugins,
          legend: {
            display: false,
          },
        },
      },
    });

    // Key usage chart
    state.charts.keyUsage = new Chart(elements.keyUsageChart, {
      type: "pie",
      data: {
        labels: [],
        datasets: [
          {
            data: [],
            backgroundColor: Object.values(CONFIG.chartColors).map(
              (c) => c.primary
            ),
            borderColor: document.documentElement.classList.contains("dark")
              ? "rgba(15, 23, 42, 1)"
              : "white",
            borderWidth: 2,
          },
        ],
      },
      options: {
        ...commonOptions,
        plugins: {
          ...commonOptions.plugins,
          legend: {
            position: "right",
            labels: {
              color: document.documentElement.classList.contains("dark")
                ? "#e2e8f0"
                : "#1e293b",
              font: {
                family:
                  "'Nunito', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
                size: 11,
              },
              boxWidth: 12,
              padding: 8,
            },
          },
        },
      },
    });
  },

  // Update all charts with current data
  updateCharts() {
    if (!state.analytics) return;

    const data = state.analytics.data;

    // Traffic chart (requests and errors over time)
    state.charts.traffic.data.labels = data.time_intervals;
    state.charts.traffic.data.datasets[0].data = data.requests_over_time;
    state.charts.traffic.data.datasets[1].data = data.errors_over_time;
    state.charts.traffic.update();

    // Response time chart
    state.charts.responseTime.data.labels = data.time_intervals;
    state.charts.responseTime.data.datasets[0].data = data.avg_response_times;
    state.charts.responseTime.update();

    // Status code distribution chart
    const statusCodes = Object.entries(
      data.status_code_distribution || {}
    ).sort(([a], [b]) => parseInt(a) - parseInt(b));

    state.charts.statusCode.data.labels = statusCodes.map(
      ([code]) => `Status ${code}`
    );
    state.charts.statusCode.data.datasets[0].data = statusCodes.map(
      ([, count]) => count
    );
    state.charts.statusCode.data.datasets[0].backgroundColor = statusCodes.map(
      ([code]) => utils.getStatusCodeColor(code)
    );
    state.charts.statusCode.update();

    // API distribution chart
    const apiDistribution = Object.entries(data.api_distribution || {})
      .sort(([, a], [, b]) => b - a)
      .slice(0, CONFIG.maxItemsInCharts);

    state.charts.apiDistribution.data.labels = apiDistribution.map(
      ([api]) => api
    );
    state.charts.apiDistribution.data.datasets[0].data = apiDistribution.map(
      ([, count]) => count
    );
    state.charts.apiDistribution.data.datasets[0].backgroundColor =
      apiDistribution.map((_, i) => utils.randomColor(i));
    state.charts.apiDistribution.update();

    // Key usage chart
    const keyDistribution = Object.entries(data.key_distribution || {})
      .sort(([, a], [, b]) => b - a)
      .slice(0, CONFIG.maxItemsInCharts);

    state.charts.keyUsage.data.labels = keyDistribution.map(([key]) =>
      utils.truncate(key, 16)
    );
    state.charts.keyUsage.data.datasets[0].data = keyDistribution.map(
      ([, count]) => count
    );
    state.charts.keyUsage.update();
  },

  // Update theme for charts when theme changes
  updateChartsTheme() {
    const isDark = document.documentElement.classList.contains("dark");
    const textColor = isDark ? "#e2e8f0" : "#1e293b";
    const gridColor = isDark
      ? "rgba(71, 85, 105, 0.2)"
      : "rgba(203, 213, 225, 0.5)";
    const backgroundColor = isDark
      ? "rgba(15, 23, 42, 0.95)"
      : "rgba(255, 255, 255, 0.95)";

    // Update common chart elements
    Object.values(state.charts).forEach((chart) => {
      // Update grid colors
      if (chart.options.scales) {
        for (const axisKey in chart.options.scales) {
          if (chart.options.scales[axisKey].grid) {
            chart.options.scales[axisKey].grid.color = gridColor;
          }
          if (chart.options.scales[axisKey].ticks) {
            chart.options.scales[axisKey].ticks.color = isDark
              ? "#cbd5e1"
              : "#475569";
          }
        }
      }

      // Update legend colors
      if (chart.options.plugins.legend && chart.options.plugins.legend.labels) {
        chart.options.plugins.legend.labels.color = textColor;
      }

      // Update tooltip colors
      if (chart.options.plugins.tooltip) {
        chart.options.plugins.tooltip.backgroundColor = backgroundColor;
        chart.options.plugins.tooltip.titleColor = textColor;
        chart.options.plugins.tooltip.bodyColor = isDark
          ? "#cbd5e1"
          : "#475569";
        chart.options.plugins.tooltip.borderColor = isDark
          ? "rgba(30, 41, 59, 0.5)"
          : "rgba(226, 232, 240, 0.5)";
      }

      // Update border colors for pie/doughnut charts
      if (chart.config.type === "pie" || chart.config.type === "doughnut") {
        chart.data.datasets[0].borderColor = isDark
          ? "rgba(15, 23, 42, 1)"
          : "white";
      }

      // Update bar borders
      if (chart.config.type === "bar") {
        chart.data.datasets[0].borderColor = isDark
          ? "rgba(15, 23, 42, 1)"
          : "white";
      }

      chart.update();
    });
  },
};

// Event handlers
const events = {
  // Set up all event listeners
  setupEventListeners() {
    // Refresh button
    elements.refreshButton.addEventListener("click", () => {
      refreshData();
    });

    // Reset metrics button
    if (elements.resetMetricsBtn) {
      elements.resetMetricsBtn.addEventListener("click", () => {
        if (
          confirm(
            "Are you sure you want to reset all metrics? This cannot be undone."
          )
        ) {
          apiService.resetMetrics().then(() => {
            refreshData();
          });
        }
      });
    }

    // Clear all queues button
    if (elements.clearAllQueuesBtn) {
      elements.clearAllQueuesBtn.addEventListener("click", () => {
        if (confirm("Are you sure you want to clear all queues?")) {
          apiService.clearAllQueues().then(() => {
            refreshData();
          });
        }
      });
    }

    // API search input
    elements.apiSearch.addEventListener("input", () => {
      ui.renderApiTable();
    });

    // History search input
    elements.historySearch.addEventListener("input", () => {
      ui.renderHistoryTable();
    });

    // Filter change events
    elements.apiFilter.addEventListener("change", () => {
      state.filters.apiName = elements.apiFilter.value;
      // Reset key filter when API changes
      if (state.filters.apiName !== "all") {
        state.filters.keyId = "all";
      }
      updateFilters();
    });

    elements.keyFilter.addEventListener("change", () => {
      state.filters.keyId = elements.keyFilter.value;
      updateFilters();
    });

    elements.timeRange.addEventListener("change", () => {
      state.filters.timeRange = elements.timeRange.value;
      updateFilters();
    });

    // Theme toggle
    elements.themeToggle.addEventListener("click", () => {
      document.documentElement.classList.toggle("dark");
      localStorage.setItem(
        "theme",
        document.documentElement.classList.contains("dark") ? "dark" : "light"
      );

      // Add rotation to the button
      elements.themeToggle.classList.add("rotate-180");
      setTimeout(() => {
        elements.themeToggle.classList.remove("rotate-180");
      }, 300);

      // Update charts for the new theme
      ui.updateChartsTheme();
    });

    // Modal close button
    elements.closeModal.addEventListener("click", () => {
      ui.hideApiDetails();
    });

    // Close modal when clicking outside
    elements.apiDetailsModal.addEventListener("click", (e) => {
      if (e.target === elements.apiDetailsModal) {
        ui.hideApiDetails();
      }
    });

    // Escape key to close modal
    document.addEventListener("keydown", (e) => {
      if (
        e.key === "Escape" &&
        !elements.apiDetailsModal.classList.contains("hidden")
      ) {
        ui.hideApiDetails();
      }
    });

    // Dynamic queue clear buttons (will be handled by event delegation)
    elements.queueContainer.addEventListener("click", (e) => {
      if (e.target.classList.contains("clear-queue-btn")) {
        const apiName = e.target.getAttribute("data-api");
        apiService.clearQueue(apiName).then(() => {
          refreshData();
        });
      }
    });
  },
};

// Main refresh function
async function refreshData() {
  try {
    // Show loading indicators
    // You could add skeleton loading states here

    // Fetch all data in parallel
    const [metricsData, historyData, queueData] = await Promise.all([
      apiService.fetchMetrics(),
      apiService.fetchHistory(),
      apiService.fetchQueueStatus(),
    ]);

    // Fetch analytics data with current filters
    const analyticsData = await apiService.fetchAnalytics(
      state.filters.apiName,
      state.filters.keyId,
      state.filters.timeRange
    );

    // Update UI components
    ui.updateGlobalStats();
    ui.updateFilterDropdowns();
    ui.renderApiTable();
    ui.renderHistoryTable();
    ui.renderQueueStatus();
    ui.updateCharts();

    // Update last updated indicator
    elements.lastUpdated.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    console.error("Error refreshing data:", error);
    utils.showToast("Failed to refresh dashboard data", "error");
  }
}

// Update filters and refresh analytics
async function updateFilters() {
  try {
    const analyticsData = await apiService.fetchAnalytics(
      state.filters.apiName,
      state.filters.keyId,
      state.filters.timeRange
    );

    ui.updateFilterDropdowns();
    ui.updateCharts();
  } catch (error) {
    console.error("Error updating filters:", error);
    utils.showToast("Failed to update filters", "error");
  }
}

// Initialize the application
function initializeApp() {
  // Cache DOM elements
  ui.cacheElements();

  // Check for saved theme preference
  const savedTheme = localStorage.getItem("theme");
  if (
    savedTheme === "dark" ||
    (!savedTheme && window.matchMedia("(prefers-color-scheme: dark)").matches)
  ) {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }

  // Initialize charts
  ui.initCharts();

  // Set up event listeners
  events.setupEventListeners();

  // Fetch initial data
  refreshData();

  // Set up auto-refresh timer
  state.refreshTimer = setInterval(refreshData, CONFIG.refreshInterval);
}

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", initializeApp);
