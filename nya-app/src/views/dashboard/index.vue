<script setup lang="ts">
import { useDevice } from '@/hooks/useDevice';
import { useAnalyticsStore } from '@/stores/modules/analytics';
import { useHistoryStore } from '@/stores/modules/history';
import { useMetricsStore } from '@/stores/modules/metrics';
import { useQueueStore } from '@/stores/modules/queue';
import { storeToRefs } from 'pinia';
import { onMounted, onUnmounted } from 'vue';

import Analysis from './components/Analysis/index.vue';
import apiDetails from './components/apiDetails/index.vue';
import fixTool from './components/fixTool/index.vue';
import HistoryRequests from './components/HistoryRequests/index.vue';
import Queue from './components/Queue/index.vue';
import topDetails from './components/topDetails/index.vue';

const { isMobile } = useDevice();
const metricsStore = useMetricsStore();
const historyStore = useHistoryStore();
const queueStore = useQueueStore();
const analyticsStore = useAnalyticsStore();
const { currentFilters } = storeToRefs(analyticsStore);

let metricsTimer: number | undefined;
let historyTimer: number | undefined;
let queueTimer: number | undefined;
let analyticsTimer: number | undefined;

// Real-time data update intervals (in milliseconds)
const UPDATE_INTERVALS = {
  metrics: 10000,
  history: 10000,
  queue: 10000,
  analytics: 10000
};

/**
 * Initialize real-time data updates
 */
const initRealTimeUpdates = async (): Promise<void> => {
  // Initial data fetch
  await Promise.allSettled([
    historyStore.fetchHistory(),
    queueStore.fetchQueue(),
    analyticsStore.fetchAnalytics(
      currentFilters.value.selectedTime,
      currentFilters.value.selectedApi,
      currentFilters.value.selectedKey
    )
  ]);

  // Set up periodic updates
  metricsTimer = window.setInterval(async () => {
    try {
      await metricsStore.fetchMetrics();
    } catch (error) {
      console.error('Failed to update metrics:', error);
    }
  }, UPDATE_INTERVALS.metrics);

  historyTimer = window.setInterval(async () => {
    try {
      await historyStore.fetchHistory();
    } catch (error) {
      console.error('Failed to update history:', error);
    }
  }, UPDATE_INTERVALS.history);

  queueTimer = window.setInterval(async () => {
    try {
      await queueStore.fetchQueue();
    } catch (error) {
      console.error('Failed to update queue:', error);
    }
  }, UPDATE_INTERVALS.queue);

  analyticsTimer = window.setInterval(async () => {
    try {
      await analyticsStore.fetchAnalytics(
        currentFilters.value.selectedTime,
        currentFilters.value.selectedApi,
        currentFilters.value.selectedKey
      );
    } catch (error) {
      console.error('Failed to update analytics:', error);
    }
  }, UPDATE_INTERVALS.metrics);
};

/**
 * Cleanup timers
 */
const cleanupTimers = (): void => {
  if (metricsTimer) {
    clearInterval(metricsTimer);
    metricsTimer = undefined;
  }
  if (historyTimer) {
    clearInterval(historyTimer);
    historyTimer = undefined;
  }
  if (queueTimer) {
    clearInterval(queueTimer);
    queueTimer = undefined;
  }
  if (analyticsTimer) {
    clearInterval(analyticsTimer);
    analyticsTimer = undefined;
  }
};

// Lifecycle hooks
onMounted(() => {
  // Initialize metrics timers (for uptime display)
  metricsStore.initializeTimers();
  // Start real-time data updates
  initRealTimeUpdates();
});



onUnmounted(() => {
  // Cleanup all timers
  cleanupTimers();
  metricsStore.cleanupTimers();
});
</script>

<template>
  <div class="dashboard-page relative">
    <div class="fixed-tool-wrapper" :class="{ 'mobile-mode': isMobile, 'desktop-mode': !isMobile }">
      <fixTool />
    </div>
    <div class="dashboard-container">
      <topDetails />
      <Analysis />
      <apiDetails />
      <Queue />
      <HistoryRequests />
    </div>
  </div>
</template>

<style scoped>
.fixed-tool-wrapper {
  z-index: 100;
}

.mobile-mode {
  position: sticky;
  top: 0px;
  width: 100%;
  display: flex;
  justify-content: center;
  padding: 8px 0;
}

.desktop-mode {
  position: fixed;
  top: 65px;
  right: 25px;
  width: auto;
}
</style>
