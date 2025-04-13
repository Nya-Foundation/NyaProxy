// NyaProxy Dashboard JavaScript

// Theme toggle functionality
document.addEventListener("DOMContentLoaded", () => {
  // Theme management
  const themeToggle = document.getElementById("theme-toggle");
  const moonIcon = themeToggle.querySelector(".dark\\:hidden"); // Moon icon shown in light mode
  const sunIcon = themeToggle.querySelector(".hidden.dark\\:block"); // Sun icon shown in dark mode

  // Function to set theme
  const setTheme = (isDark) => {
    if (isDark) {
      document.documentElement.classList.add("dark");
      moonIcon.classList.add("hidden");
      sunIcon.classList.remove("hidden");
    } else {
      document.documentElement.classList.remove("dark");
      moonIcon.classList.remove("hidden");
      sunIcon.classList.add("hidden");
    }
    localStorage.theme = isDark ? "dark" : "light";
  };

  // Check for saved theme preference or respect OS preference
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const savedTheme = localStorage.getItem("theme");

  if (savedTheme === "dark" || (!savedTheme && prefersDark)) {
    setTheme(true);
  } else {
    setTheme(false);
  }

  // Theme toggle button
  themeToggle.addEventListener("click", () => {
    const isDark = document.documentElement.classList.contains("dark");
    setTheme(!isDark);

    // Add a subtle animation effect
    themeToggle.classList.add("rotate-180");
    setTimeout(() => {
      themeToggle.classList.remove("rotate-180");
    }, 300);
  });

  // Listen for OS theme changes
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", (e) => {
      if (!localStorage.theme) {
        // Only auto-switch if user hasn't set a preference
        setTheme(e.matches);
      }
    });

  // Initialize dashboard
  initDashboard();
});

// API endpoints
const API_ENDPOINTS = {
  METRICS: "/dashboard/api/metrics",
  QUEUE: "/dashboard/api/queue",
  HISTORY: "/dashboard/api/history",
  RESET_METRICS: "/dashboard/api/metrics/reset",
  CLEAR_QUEUE: "/dashboard/api/queue/clear",
  CLEAR_SPECIFIC_QUEUE: (apiName) => `/dashboard/api/queue/clear/${apiName}`,
};

// Dashboard initialization
function initDashboard() {
  // Set up header blur on scroll
  setupHeaderBlur();

  // Set up refresh functionality
  setupRefreshButton();

  // Set up API search functionality
  const apiSearch = document.getElementById("api-search");
  apiSearch.addEventListener("input", filterApiTable);

  // Set up reset metrics button
  const resetMetricsBtn = document.getElementById("reset-metrics-btn");
  if (resetMetricsBtn) {
    resetMetricsBtn.addEventListener("click", resetMetrics);
  }

  // Set up clear all queues button
  const clearAllQueuesBtn = document.getElementById("clear-all-queues-btn");
  if (clearAllQueuesBtn) {
    clearAllQueuesBtn.addEventListener("click", clearAllQueues);
  }

  // Set up modal close button
  setupModalClose();

  // Initial data fetch
  fetchDashboardData();

  // Set up auto-refresh every 30 seconds
  setInterval(fetchDashboardData, 30000);
}

// Setup refresh button functionality
function setupRefreshButton() {
  const refreshButton = document.getElementById("refresh-button");
  refreshButton.addEventListener("click", () => {
    // Show loading spinner in the refresh button
    refreshButton.innerHTML = '<div class="loading-spinner"></div>';
    refreshButton.disabled = true;

    fetchDashboardData()
      .then(() => {
        // Restore original refresh button after data is loaded
        refreshButton.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd" />
        </svg>
      `;
        refreshButton.disabled = false;
        showToast("Dashboard refreshed", "success");
      })
      .catch((error) => {
        console.error("Failed to refresh dashboard:", error);
        // Restore original refresh button if there's an error
        refreshButton.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd" />
        </svg>
      `;
        refreshButton.disabled = false;
        showToast("Failed to refresh dashboard", "error");
      });
  });
}

// Setup modal close functionality
function setupModalClose() {
  const closeModalBtn = document.getElementById("close-modal");
  closeModalBtn.addEventListener("click", () => {
    const modal = document.getElementById("api-details-modal");
    modal.classList.add("hidden");
    // Add fade-out animation
    modal.style.opacity = 0;
  });

  // Close modal when clicking outside
  window.addEventListener("click", (e) => {
    const modal = document.getElementById("api-details-modal");
    if (e.target === modal) {
      modal.classList.add("hidden");
      // Add fade-out animation
      modal.style.opacity = 0;
    }
  });
}

// Setup header blur on scroll
function setupHeaderBlur() {
  const header = document.querySelector("header");

  window.addEventListener("scroll", () => {
    if (window.scrollY > 10) {
      header.classList.add("shadow-sm");
    } else {
      header.classList.remove("shadow-sm");
    }
  });
}

// Fetch all dashboard data
async function fetchDashboardData() {
  try {
    // Fetch all data in parallel for better performance
    const [metricsResponse, queueResponse, historyResponse] = await Promise.all(
      [
        fetch(API_ENDPOINTS.METRICS),
        fetch(API_ENDPOINTS.QUEUE),
        fetch(API_ENDPOINTS.HISTORY),
      ]
    );

    // Check for response errors
    if (!metricsResponse.ok) {
      throw new Error(`Metrics API error: ${metricsResponse.status}`);
    }
    if (!queueResponse.ok) {
      throw new Error(`Queue API error: ${queueResponse.status}`);
    }
    if (!historyResponse.ok) {
      throw new Error(`History API error: ${historyResponse.status}`);
    }

    // Parse JSON responses
    const metricsData = await metricsResponse.json();
    const queueData = await queueResponse.json();
    const historyData = await historyResponse.json();

    // Update the dashboard with the fetched data
    updateDashboard(metricsData, queueData, historyData);

    // Update last updated time
    updateLastUpdatedTime();

    return Promise.resolve();
  } catch (error) {
    console.error("Error fetching dashboard data:", error);
    showToast(`Failed to fetch dashboard data: ${error.message}`, "error");
    return Promise.reject(error);
  }
}

// Update the dashboard with the fetched data
function updateDashboard(metricsData, queueData, historyData) {
  // Update global stats
  updateGlobalStats(metricsData.global);

  // Update API table
  updateApiTable(metricsData.apis);

  // Update responsive API cards for mobile
  updateApiCards(metricsData.apis);

  // Update API filter options
  updateApiFilterOptions(metricsData.apis);

  // Update traffic chart
  updateTrafficChart(metricsData.apis);

  // Update queue status
  updateQueueStatus(queueData.queue_sizes);

  // Update request history
  updateRequestHistory(historyData.history);

  // Update responsive history cards for mobile
  updateHistoryCards(historyData.history);
}

// Update global statistics
function updateGlobalStats(globalStats) {
  // Use number animation for statistics
  animateNumber("total-requests", 0, globalStats.total_requests);
  animateNumber("total-errors", 0, globalStats.total_errors);
  animateNumber("total-rate-limits", 0, globalStats.total_rate_limit_hits);

  document.getElementById("uptime").textContent = formatUptime(
    globalStats.uptime_seconds
  );

  // Update progress bars with animation
  const maxValue = Math.max(globalStats.total_requests, 1);
  animateProgressBar("total-requests-bar", 0, 100);
  animateProgressBar(
    "total-errors-bar",
    0,
    (globalStats.total_errors / maxValue) * 100
  );
  animateProgressBar(
    "total-rate-limits-bar",
    0,
    (globalStats.total_rate_limit_hits / maxValue) * 100
  );
}

// Animate number counting up
function animateNumber(elementId, start, end) {
  const element = document.getElementById(elementId);
  if (!element) return;

  const duration = 1000; // milliseconds
  const frameRate = 60;
  const increment = (end - start) / (duration / (1000 / frameRate));

  let current = start;
  const timer = setInterval(() => {
    current += increment;
    if (
      (increment > 0 && current >= end) ||
      (increment < 0 && current <= end)
    ) {
      clearInterval(timer);
      current = end;
    }
    element.textContent = Math.round(current).toLocaleString();
  }, 1000 / frameRate);
}

// Animate progress bar
function animateProgressBar(elementId, start, end) {
  const element = document.getElementById(elementId);
  if (!element) return;

  const duration = 1000; // milliseconds
  const frameRate = 60;
  const increment = (end - start) / (duration / (1000 / frameRate));

  let current = start;
  const timer = setInterval(() => {
    current += increment;
    if (
      (increment > 0 && current >= end) ||
      (increment < 0 && current <= end)
    ) {
      clearInterval(timer);
      current = end;
    }
    element.style.width = `${current}%`;
  }, 1000 / frameRate);
}

// Update API table
function updateApiTable(apis) {
  const tableBody = document.getElementById("api-table-body");
  if (!tableBody) return;

  tableBody.innerHTML = "";

  if (Object.keys(apis).length === 0) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td colspan="6" class="px-6 py-4 text-center text-sm text-slate-500 dark:text-slate-400">
        No API data available
      </td>
    `;
    tableBody.appendChild(row);
    return;
  }

  Object.entries(apis).forEach(([apiName, apiData]) => {
    const row = document.createElement("tr");
    row.className =
      "hover:bg-slate-50/50 dark:hover:bg-slate-700/50 transition-colors duration-150";
    row.dataset.apiName = apiName;

    // Calculate error rate
    const errorRate =
      apiData.requests > 0 ? (apiData.errors / apiData.requests) * 100 : 0;
    const errorRateClass =
      errorRate > 20
        ? "text-red-500"
        : errorRate > 5
        ? "text-yellow-500"
        : "text-green-500";

    row.innerHTML = `
      <td class="px-6 py-4">
        <div class="flex items-center">
          <div class="h-2.5 w-2.5 rounded-full ${getApiStatusColor(
            apiData
          )} mr-2.5"></div>
          <span class="font-medium">${apiName}</span>
        </div>
      </td>
      <td class="px-6 py-4">${apiData.requests.toLocaleString()}</td>
      <td class="px-6 py-4">
        <span class="${errorRateClass} font-medium">${apiData.errors.toLocaleString()} <span class="text-xs font-normal">(${errorRate.toFixed(
      1
    )}%)</span></span>
      </td>
      <td class="px-6 py-4">${apiData.avg_response_time_ms.toFixed(2)} ms</td>
      <td class="px-6 py-4 whitespace-nowrap text-xs">${formatTimestamp(
        apiData.last_request_time
      )}</td>
      <td class="px-6 py-4">
        <div class="flex space-x-2">
          <button class="btn-modern bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 text-slate-800 dark:text-slate-200 text-xs py-1 px-2 rounded-lg transition-colors duration-200 view-details-btn">
            View Details
          </button>
          <button class="btn-modern bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-800/30 text-xs py-1 px-2 rounded-lg transition-colors duration-200 clear-queue-btn" style="display: ${
            document.getElementById("reset-metrics-btn").style.display
          }">
            Clear
          </button>
        </div>
      </td>
    `;

    tableBody.appendChild(row);

    // Add event listener for view details button
    row.querySelector(".view-details-btn").addEventListener("click", () => {
      showApiDetailsModal(apiName, apiData);
    });

    // Add event listener for clear queue button
    const clearQueueBtn = row.querySelector(".clear-queue-btn");
    if (clearQueueBtn) {
      clearQueueBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        clearQueue(apiName);
      });
    }
  });
}

// Create responsive API cards for mobile view
function updateApiCards(apis) {
  const cardsContainer = document.getElementById("api-cards-container");
  if (!cardsContainer) return;

  cardsContainer.innerHTML = "";

  if (Object.keys(apis).length === 0) {
    const emptyCard = document.createElement("div");
    emptyCard.className =
      "modern-card p-4 text-center text-sm text-slate-500 dark:text-slate-400";
    emptyCard.textContent = "No API data available";
    cardsContainer.appendChild(emptyCard);
    return;
  }

  Object.entries(apis).forEach(([apiName, apiData]) => {
    // Calculate error rate
    const errorRate =
      apiData.requests > 0 ? (apiData.errors / apiData.requests) * 100 : 0;
    const errorRateClass =
      errorRate > 20
        ? "text-red-500"
        : errorRate > 5
        ? "text-yellow-500"
        : "text-green-500";

    const card = document.createElement("div");
    card.className = "modern-card p-4";
    card.dataset.apiName = apiName;

    card.innerHTML = `
      <div class="responsive-table-card-header flex items-center">
        <div class="h-2.5 w-2.5 rounded-full ${getApiStatusColor(
          apiData
        )} mr-2"></div>
        <span class="font-medium">${apiName}</span>
      </div>
      <div class="responsive-table-card-content mt-3">
        <div>
          <div class="responsive-table-card-label">Requests</div>
          <div>${apiData.requests.toLocaleString()}</div>
        </div>
        <div>
          <div class="responsive-table-card-label">Errors</div>
          <div class="${errorRateClass}">${apiData.errors.toLocaleString()} <span class="text-xs">(${errorRate.toFixed(
      1
    )}%)</span></div>
        </div>
        <div>
          <div class="responsive-table-card-label">Avg Response</div>
          <div>${apiData.avg_response_time_ms.toFixed(2)} ms</div>
        </div>
        <div>
          <div class="responsive-table-card-label">Last Request</div>
          <div class="text-xs">${formatTimestamp(
            apiData.last_request_time
          )}</div>
        </div>
      </div>
      <div class="mt-3 flex space-x-2">
        <button class="btn-modern bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 text-slate-800 dark:text-slate-200 text-xs py-1 px-2 rounded-lg transition-colors duration-200 flex-1 view-details-btn">
          View Details
        </button>
        <button class="btn-modern bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-800/30 text-xs py-1 px-2 rounded-lg transition-colors duration-200 clear-queue-btn" style="display: ${
          document.getElementById("reset-metrics-btn").style.display
        }">
          Clear
        </button>
      </div>
    `;

    cardsContainer.appendChild(card);

    // Add event listener for view details button
    card.querySelector(".view-details-btn").addEventListener("click", () => {
      showApiDetailsModal(apiName, apiData);
    });

    // Add event listener for clear queue button
    const clearQueueBtn = card.querySelector(".clear-queue-btn");
    if (clearQueueBtn) {
      clearQueueBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        clearQueue(apiName);
      });
    }
  });

  // Apply filter to cards as well
  filterApiCards();
}

// Filter API table based on search input
function filterApiTable() {
  const searchTerm = document.getElementById("api-search").value.toLowerCase();
  const rows = document.querySelectorAll("#api-table-body tr");

  rows.forEach((row) => {
    const apiName = row.dataset.apiName;
    if (!apiName) return; // Skip rows without API name

    if (apiName.toLowerCase().includes(searchTerm)) {
      row.style.display = "";
    } else {
      row.style.display = "none";
    }
  });

  // Also filter the mobile cards
  filterApiCards();
}

// Filter API cards based on search input
function filterApiCards() {
  const searchTerm = document.getElementById("api-search").value.toLowerCase();
  const cards = document.querySelectorAll("#api-cards-container > div");

  cards.forEach((card) => {
    const apiName = card.dataset.apiName;
    if (!apiName) return; // Skip cards without API name

    if (apiName.toLowerCase().includes(searchTerm)) {
      card.style.display = "";
    } else {
      card.style.display = "none";
    }
  });
}

// Update API filter options
function updateApiFilterOptions(apis) {
  const apiFilter = document.getElementById("api-filter");
  if (!apiFilter) return;

  const currentValue = apiFilter.value;

  // Clear existing options except "All APIs"
  while (apiFilter.options.length > 1) {
    apiFilter.remove(1);
  }

  // Add options for each API
  Object.keys(apis).forEach((apiName) => {
    const option = document.createElement("option");
    option.value = apiName;
    option.textContent = apiName;
    apiFilter.appendChild(option);
  });

  // Restore selected value if it still exists
  if (
    Array.from(apiFilter.options).some(
      (option) => option.value === currentValue
    )
  ) {
    apiFilter.value = currentValue;
  }

  // Add event listener for filter change
  apiFilter.removeEventListener("change", updateTrafficChart);
  apiFilter.addEventListener("change", updateTrafficChart);
}

// Update traffic chart with actual history data
async function updateTrafficChart() {
  const apiFilter = document.getElementById("api-filter");
  if (!apiFilter) return;

  const timeRange = document.getElementById("time-range");
  const selectedApi = apiFilter.value;
  const selectedTimeRange = timeRange ? timeRange.value : "24h";

  try {
    // Fetch data
    const [historyResponse] = await Promise.all([fetch(API_ENDPOINTS.HISTORY)]);

    if (!historyResponse.ok) {
      throw new Error("Failed to fetch data for chart");
    }

    const historyData = await historyResponse.json();
    const requestHistory = historyData.history.filter(
      (item) => item.type === "request"
    );

    // Process history data to generate time-series data
    const processedData = processHistoryDataForChart(
      requestHistory,
      selectedApi,
      selectedTimeRange
    );

    const ctx = document.getElementById("traffic-chart");
    if (!ctx) return;

    // Destroy existing chart if it exists
    if (window.trafficChart) {
      window.trafficChart.destroy();
    }

    // Create the chart
    window.trafficChart = new Chart(ctx.getContext("2d"), {
      type: "line",
      data: processedData,
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: {
            display: true,
            text:
              selectedApi === "all"
                ? "All APIs Traffic"
                : `${selectedApi} API Traffic`,
            font: {
              size: 16,
              weight: "bold",
            },
          },
          legend: {
            position: "bottom",
          },
          tooltip: {
            mode: "index",
            intersect: false,
          },
        },
        scales: {
          x: {
            title: {
              display: true,
              text: "Time",
            },
          },
          y: {
            beginAtZero: true,
            title: {
              display: true,
              text: "Requests",
            },
          },
        },
      },
    });
  } catch (error) {
    console.error("Error updating traffic chart:", error);
    showToast("Failed to update traffic chart", "error");
  }
}

// Process history data into chart format
function processHistoryDataForChart(history, selectedApi, timeRange) {
  // Filter history entries based on selected time range
  const filteredHistory = filterHistoryByTimeRange(history, timeRange);

  // Group history by time intervals
  const timeIntervals = generateTimeIntervals(timeRange);
  const groupedData = groupHistoryByTimeIntervals(
    filteredHistory,
    timeIntervals,
    selectedApi
  );

  // Format data for Chart.js
  return formatDataForChart(groupedData, timeIntervals, selectedApi);
}

// Filter history by time range
function filterHistoryByTimeRange(history, timeRange) {
  if (!history || history.length === 0) return [];

  const now = Date.now() / 1000;
  let cutoffTime;

  switch (timeRange) {
    case "1h":
      cutoffTime = now - 3600; // 1 hour
      break;
    case "24h":
      cutoffTime = now - 86400; // 24 hours
      break;
    case "7d":
      cutoffTime = now - 604800; // 7 days
      break;
    case "30d":
      cutoffTime = now - 2592000; // 30 days
      break;
    default:
      cutoffTime = 0; // All time
  }

  return history.filter((entry) => entry.timestamp >= cutoffTime);
}

// Generate time intervals based on selected range
function generateTimeIntervals(timeRange) {
  const now = Date.now();
  const intervals = [];
  let intervalCount, intervalSize;

  switch (timeRange) {
    case "1h":
      intervalCount = 12;
      intervalSize = 5 * 60 * 1000; // 5 minutes
      break;
    case "24h":
      intervalCount = 24;
      intervalSize = 60 * 60 * 1000; // 1 hour
      break;
    case "7d":
      intervalCount = 7;
      intervalSize = 24 * 60 * 60 * 1000; // 1 day
      break;
    case "30d":
      intervalCount = 30;
      intervalSize = 24 * 60 * 60 * 1000; // 1 day
      break;
    default:
      intervalCount = 24;
      intervalSize = 60 * 60 * 1000; // Default to hourly for "all"
  }

  for (let i = intervalCount - 1; i >= 0; i--) {
    const time = new Date(now - i * intervalSize);
    intervals.push({
      time: time,
      label: formatIntervalLabel(time, timeRange),
      startTimestamp: time.getTime() / 1000 - intervalSize / 1000,
      endTimestamp: time.getTime() / 1000,
    });
  }

  return intervals;
}

// Format interval label based on time range
function formatIntervalLabel(time, timeRange) {
  switch (timeRange) {
    case "1h":
      return time.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
    case "24h":
      return time.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
    case "7d":
    case "30d":
      return time.toLocaleDateString([], { month: "short", day: "numeric" });
    default:
      return time.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
  }
}

// Group history by time intervals and APIs
function groupHistoryByTimeIntervals(history, intervals, selectedApi) {
  // Initialize data structure
  const apiData = {};

  // Process history entries
  history.forEach((entry) => {
    if (entry.type !== "request" && entry.type !== "response") return;

    const apiName = entry.api_name;

    // Skip if we're filtering for a specific API and this is not it
    if (selectedApi !== "all" && apiName !== selectedApi) return;

    // Find which interval this entry belongs to
    const interval = intervals.find(
      (int) =>
        entry.timestamp >= int.startTimestamp &&
        entry.timestamp <= int.endTimestamp
    );

    if (!interval) return;

    // Initialize API data if needed
    if (!apiData[apiName]) {
      apiData[apiName] = intervals.map(() => 0);
    }

    // Increment the count for this API in this interval
    const intervalIndex = intervals.indexOf(interval);
    if (intervalIndex >= 0) {
      apiData[apiName][intervalIndex]++;
    }
  });

  return apiData;
}

// Format grouped data for Chart.js
function formatDataForChart(groupedData, intervals, selectedApi) {
  const datasets = [];
  const labels = intervals.map((int) => int.label);

  // If showing a specific API
  if (selectedApi !== "all") {
    const requestsData = groupedData[selectedApi] || intervals.map(() => 0);

    return {
      labels,
      datasets: [
        {
          label: "Requests",
          data: requestsData,
          borderColor: "rgb(59, 130, 246)", // Blue
          backgroundColor: "rgba(59, 130, 246, 0.2)",
          tension: 0.4,
          fill: true,
        },
      ],
    };
  }

  // If showing all APIs
  Object.entries(groupedData).forEach(([apiName, data], index) => {
    // Generate a color based on index
    const hue = (index * 137) % 360; // Golden angle approximation
    const color = `hsl(${hue}, 70%, 60%)`;

    datasets.push({
      label: apiName,
      data: data,
      borderColor: color,
      backgroundColor: `${color}33`, // Add transparency
      tension: 0.4,
      fill: false,
    });
  });

  return {
    labels,
    datasets,
  };
}

// Update queue status
function updateQueueStatus(queueSizes) {
  const queueContainer = document.getElementById("queue-container");
  if (!queueContainer) return;

  queueContainer.innerHTML = "";

  if (!queueSizes || Object.keys(queueSizes).length === 0) {
    const emptyCard = document.createElement("div");
    emptyCard.className =
      "bg-white dark:bg-slate-800 rounded-lg shadow-sm p-4 border border-slate-200 dark:border-slate-700";
    emptyCard.innerHTML = `
            <p class="text-center text-slate-500 dark:text-slate-400">No queue data available</p>
        `;
    queueContainer.appendChild(emptyCard);
    return;
  }

  Object.entries(queueSizes).forEach(([apiName, queueSize]) => {
    const card = document.createElement("div");
    card.className =
      "bg-white dark:bg-slate-800 rounded-lg shadow-sm p-4 border border-slate-200 dark:border-slate-700 api-card";

    // Calculate queue fill percentage
    const maxQueueSize = 100; // Assuming a max queue size of 100 for visualization
    const fillPercentage = Math.min((queueSize / maxQueueSize) * 100, 100);

    // Determine color based on queue size
    let queueColor, queueStatus;
    if (queueSize === 0) {
      queueColor = "bg-green-500";
      queueStatus = "Empty";
    } else if (queueSize < 10) {
      queueColor = "bg-blue-500";
      queueStatus = "Low";
    } else if (queueSize < 50) {
      queueColor = "bg-yellow-500";
      queueStatus = "Moderate";
    } else {
      queueColor = "bg-red-500";
      queueStatus = "High";
    }

    card.innerHTML = `
            <div class="flex justify-between items-center mb-2">
                <h3 class="font-medium">${apiName}</h3>
                <span class="text-xs px-2 py-1 rounded-full bg-slate-100 dark:bg-slate-700">${queueStatus}</span>
            </div>
            <div class="h-4 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden mb-2">
                <div class="${queueColor} h-full" style="width: ${fillPercentage}%"></div>
            </div>
            <div class="flex justify-between items-center text-xs text-slate-500 dark:text-slate-400">
                <span>Queue Size: ${queueSize}</span>
                <span>${fillPercentage.toFixed(0)}% Full</span>
            </div>
        `;

    queueContainer.appendChild(card);
  });
}

// Update request history
function updateRequestHistory(history) {
  const historyTableBody = document.getElementById("history-table-body");
  if (!historyTableBody) return;

  historyTableBody.innerHTML = "";

  if (!history || history.length === 0) {
    const row = document.createElement("tr");
    row.innerHTML = `
            <td colspan="5" class="px-6 py-4 text-center text-sm text-slate-500 dark:text-slate-400">
                No request history available
            </td>
        `;
    historyTableBody.appendChild(row);
    return;
  }

  // Process only response entries for the table display
  const responseEntries = history.filter((entry) => entry.type === "response");

  responseEntries.forEach((entry) => {
    const row = document.createElement("tr");
    row.className = "hover:bg-slate-50 dark:hover:bg-slate-700/50";

    // Extract data from the entry
    const timestamp = entry.timestamp;
    const apiName = entry.api_name;
    const statusCode = entry.status_code || 0;
    const responseTime = entry.elapsed_ms || 0;
    const keyId = entry.key_id || "unknown";

    // Determine status color
    let statusClass;
    if (statusCode >= 200 && statusCode < 300) {
      statusClass = "bg-green-500";
    } else if (statusCode >= 400 && statusCode < 500) {
      statusClass = "bg-yellow-500";
    } else {
      statusClass = "bg-red-500";
    }

    // Mask API key for security
    const maskedKey = maskApiKey(keyId);

    row.innerHTML = `
            <td class="px-6 py-4 text-sm">${formatTimestamp(timestamp)}</td>
            <td class="px-6 py-4 text-sm">${apiName}</td>
            <td class="px-6 py-4">
                <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusClass} text-white">
                    ${statusCode}
                </span>
            </td>
            <td class="px-6 py-4 text-sm">${responseTime.toFixed(2)} ms</td>
            <td class="px-6 py-4 text-sm font-mono text-xs">${maskedKey}</td>
        `;

    historyTableBody.appendChild(row);
  });
}

// Create responsive history cards for mobile view
function updateHistoryCards(history) {
  const cardsContainer = document.getElementById("history-cards-container");
  if (!cardsContainer) return;

  cardsContainer.innerHTML = "";

  if (!history || history.length === 0) {
    const emptyCard = document.createElement("div");
    emptyCard.className =
      "modern-card p-4 text-center text-sm text-slate-500 dark:text-slate-400";
    emptyCard.textContent = "No request history available";
    cardsContainer.appendChild(emptyCard);
    return;
  }

  // Process only response entries for the cards display
  const responseEntries = history.filter((entry) => entry.type === "response");

  responseEntries.slice(0, 10).forEach((entry) => {
    // Extract data from the entry
    const timestamp = entry.timestamp;
    const apiName = entry.api_name;
    const statusCode = entry.status_code || 0;
    const responseTime = entry.elapsed_ms || 0;
    const keyId = entry.key_id || "unknown";

    // Determine status color
    let statusClass;
    if (statusCode >= 200 && statusCode < 300) {
      statusClass = "bg-green-500";
    } else if (statusCode >= 400 && statusCode < 500) {
      statusClass = "bg-yellow-500";
    } else {
      statusClass = "bg-red-500";
    }

    // Mask API key for security
    const maskedKey = maskApiKey(keyId);

    const card = document.createElement("div");
    card.className = "modern-card p-4";

    card.innerHTML = `
      <div class="responsive-table-card-header">
        <div class="text-xs">${formatTimestamp(timestamp)}</div>
      </div>
      <div class="responsive-table-card-content mt-3">
        <div>
          <div class="responsive-table-card-label">API</div>
          <div>${apiName}</div>
        </div>
        <div>
          <div class="responsive-table-card-label">Status</div>
          <div>
            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusClass} text-white">
              ${statusCode}
            </span>
          </div>
        </div>
        <div>
          <div class="responsive-table-card-label">Response Time</div>
          <div>${responseTime.toFixed(2)} ms</div>
        </div>
        <div>
          <div class="responsive-table-card-label">Key</div>
          <div class="text-xs font-mono">${maskedKey}</div>
        </div>
      </div>
    `;

    cardsContainer.appendChild(card);
  });
}

// Show API details modal
function showApiDetailsModal(apiName, apiData) {
  const modal = document.getElementById("api-details-modal");
  const modalTitle = document.getElementById("modal-title");
  const modalContent = document.getElementById("modal-content");

  modalTitle.textContent = `${apiName} API Details`;

  // Prepare response code distribution data
  const responseCodeLabels = Object.keys(apiData.responses || {});
  const responseCodeData = responseCodeLabels.map(
    (code) => apiData.responses[code]
  );

  // Prepare key usage data
  const keyUsageLabels = Object.keys(apiData.key_usage || {});
  const keyUsageData = keyUsageLabels.map((key) => apiData.key_usage[key]);
  const maskedKeyLabels = keyUsageLabels.map((key) => maskApiKey(key));

  modalContent.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div class="bg-slate-50 dark:bg-slate-700/50 p-4 rounded-lg">
                <h4 class="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">Response Times</h4>
                <div class="space-y-2">
                    <div class="flex justify-between">
                        <span class="text-sm">Average</span>
                        <span class="font-medium">${apiData.avg_response_time_ms.toFixed(
                          2
                        )} ms</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-sm">Minimum</span>
                        <span class="font-medium">${apiData.min_response_time_ms.toFixed(
                          2
                        )} ms</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-sm">Maximum</span>
                        <span class="font-medium">${apiData.max_response_time_ms.toFixed(
                          2
                        )} ms</span>
                    </div>
                </div>
            </div>
            <div class="bg-slate-50 dark:bg-slate-700/50 p-4 rounded-lg">
                <h4 class="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">Request Statistics</h4>
                <div class="space-y-2">
                    <div class="flex justify-between">
                        <span class="text-sm">Total Requests</span>
                        <span class="font-medium">${apiData.requests.toLocaleString()}</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-sm">Errors</span>
                        <span class="font-medium">${apiData.errors.toLocaleString()}</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-sm">Rate Limit Hits</span>
                        <span class="font-medium">${apiData.rate_limit_hits.toLocaleString()}</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-sm">Queue Hits</span>
                        <span class="font-medium">${apiData.queue_hits.toLocaleString()}</span>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
                <h4 class="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">Response Code Distribution</h4>
                <div class="h-64">
                    <canvas id="response-code-chart"></canvas>
                </div>
            </div>
            <div>
                <h4 class="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">Key Usage Distribution</h4>
                <div class="h-64">
                    <canvas id="key-usage-chart"></canvas>
                </div>
            </div>
        </div>
    `;

  modal.classList.remove("hidden");
  // Add fade-in animation
  modal.style.opacity = 0;
  setTimeout(() => {
    modal.style.transition = "opacity 0.15s ease-in-out";
    modal.style.opacity = 1;
  }, 50);

  // Create charts with a slight delay to ensure the DOM is ready
  setTimeout(() => {
    createDetailCharts(
      responseCodeLabels,
      responseCodeData,
      maskedKeyLabels,
      keyUsageData
    );
  }, 100);
}

// Create the charts for API details modal
function createDetailCharts(
  responseCodeLabels,
  responseCodeData,
  keyLabels,
  keyData
) {
  // Create response code distribution chart
  const responseCodeCtx = document.getElementById("response-code-chart");
  if (responseCodeCtx) {
    new Chart(responseCodeCtx.getContext("2d"), {
      type: "pie",
      data: {
        labels: responseCodeLabels,
        datasets: [
          {
            data: responseCodeData,
            backgroundColor: responseCodeLabels.map((code) =>
              getStatusCodeColor(Number.parseInt(code))
            ),
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "bottom",
          },
        },
      },
    });
  }

  // Create key usage distribution chart
  const keyUsageCtx = document.getElementById("key-usage-chart");
  if (keyUsageCtx) {
    new Chart(keyUsageCtx.getContext("2d"), {
      type: "pie",
      data: {
        labels: keyLabels,
        datasets: [
          {
            data: keyData,
            backgroundColor: generateColorPalette(keyLabels.length),
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "bottom",
          },
        },
      },
    });
  }
}

// Reset metrics
async function resetMetrics() {
  try {
    const response = await fetch(API_ENDPOINTS.RESET_METRICS, {
      method: "POST",
    });

    if (response.ok) {
      showToast("Metrics reset successfully", "success");
      await fetchDashboardData();
    } else {
      const data = await response.json();
      showToast(`Failed to reset metrics: ${data.error}`, "error");
    }
  } catch (error) {
    console.error("Error resetting metrics:", error);
    showToast(`Failed to reset metrics: ${error.message}`, "error");
  }
}

// Clear queue for a specific API
async function clearQueue(apiName) {
  try {
    const response = await fetch(API_ENDPOINTS.CLEAR_SPECIFIC_QUEUE(apiName), {
      method: "POST",
    });

    if (response.ok) {
      const data = await response.json();
      showToast(
        `Cleared ${data.cleared_count} items from ${apiName} queue`,
        "success"
      );
      await fetchDashboardData();
    } else {
      const data = await response.json();
      showToast(`Failed to clear queue: ${data.error}`, "error");
    }
  } catch (error) {
    console.error("Error clearing queue:", error);
    showToast(`Failed to clear queue: ${error.message}`, "error");
  }
}

// Clear all queues
async function clearAllQueues() {
  try {
    const response = await fetch(API_ENDPOINTS.CLEAR_QUEUE, {
      method: "POST",
    });

    if (response.ok) {
      const data = await response.json();
      showToast(
        `Cleared ${data.cleared_count} items from all queues`,
        "success"
      );
      await fetchDashboardData();
    } else {
      const data = await response.json();
      showToast(`Failed to clear queues: ${data.error}`, "error");
    }
  } catch (error) {
    console.error("Error clearing all queues:", error);
    showToast(`Failed to clear all queues: ${error.message}`, "error");
  }
}

// Update last updated time
function updateLastUpdatedTime() {
  const lastUpdated = document.getElementById("last-updated");
  if (!lastUpdated) return;

  const now = new Date();
  lastUpdated.textContent = `Last updated: ${now.toLocaleTimeString()}`;
}

// Show toast notification
function showToast(message, type = "success") {
  const toast = document.getElementById("toast");
  const toastMessage = document.getElementById("toast-message");
  const toastIcon = document.getElementById("toast-icon");

  if (!toast || !toastMessage || !toastIcon) return;

  // Set message
  toastMessage.textContent = message;

  // Set icon based on type
  if (type === "success") {
    toastIcon.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
            </svg>
        `;
    toastIcon.className = "mr-3 text-green-500";
  } else {
    toastIcon.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293-1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
            </svg>
        `;
    toastIcon.className = "mr-3 text-red-500";
  }

  // Show toast
  toast.classList.remove("toast-hidden");
  toast.classList.add("toast-visible");

  // Hide toast after 3 seconds
  setTimeout(() => {
    toast.classList.remove("toast-visible");
    toast.classList.add("toast-hidden");
  }, 3000);
}

// Helper functions
function formatUptime(seconds) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = Math.floor(seconds % 60);

  if (days > 0) {
    return `${days}d ${hours}h ${minutes}m`;
  } else if (hours > 0) {
    return `${hours}h ${minutes}m ${remainingSeconds}s`;
  } else if (minutes > 0) {
    return `${minutes}m ${remainingSeconds}s`;
  } else {
    return `${remainingSeconds}s`;
  }
}

function formatTimestamp(timestamp) {
  if (!timestamp) return "N/A";

  const date = new Date(timestamp * 1000);
  return date.toLocaleString();
}

function getApiStatusColor(apiData) {
  if (!apiData.last_request_time) return "bg-slate-300 dark:bg-slate-600";

  const now = Date.now() / 1000;
  const timeSinceLastRequest = now - apiData.last_request_time;

  if (timeSinceLastRequest < 60) {
    return "bg-green-500"; // Active in the last minute
  } else if (timeSinceLastRequest < 3600) {
    return "bg-blue-500"; // Active in the last hour
  } else if (timeSinceLastRequest < 86400) {
    return "bg-yellow-500"; // Active in the last day
  } else {
    return "bg-red-500"; // Inactive for more than a day
  }
}

function getApiStatusText(apiData) {
  if (!apiData.last_request_time) return "Never used";

  const now = Date.now() / 1000;
  const timeSinceLastRequest = now - apiData.last_request_time;

  if (timeSinceLastRequest < 60) {
    return "Active (last minute)";
  } else if (timeSinceLastRequest < 3600) {
    return "Active (last hour)";
  } else if (timeSinceLastRequest < 86400) {
    return "Active (last day)";
  } else {
    return "Inactive";
  }
}

function getStatusCodeColor(code) {
  if (code >= 200 && code < 300) {
    return "rgba(16, 185, 129, 0.7)"; // Green
  } else if (code >= 400 && code < 500) {
    return "rgba(245, 158, 11, 0.7)"; // Yellow
  } else {
    return "rgba(239, 68, 68, 0.7)"; // Red
  }
}

function maskApiKey(key) {
  if (!key) return "N/A";

  // If key is shorter than 8 characters, mask all but first and last
  if (key.length < 8) {
    return key.charAt(0) + "•••" + key.charAt(key.length - 1);
  }

  // Otherwise, show first 4 and last 4 characters
  return key.substring(0, 4) + "•••••••" + key.substring(key.length - 4);
}

function generateColorPalette(count) {
  const colors = [];

  for (let i = 0; i < count; i++) {
    // Generate colors using HSL for better distribution
    const hue = (i * 137) % 360; // Golden angle approximation
    colors.push(`hsla(${hue}, 70%, 60%, 0.7)`);
  }

  return colors;
}
