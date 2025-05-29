<script setup lang="ts">
import { useDevice } from '@/hooks/useDevice';
import { useTheme } from '@/hooks/useTheme';
import { useAnalyticsStore } from '@/stores/modules/analytics';
import { useHistoryStore } from '@/stores/modules/history';
import { useMetricsStore } from '@/stores/modules/metrics';
import { useQueueStore } from '@/stores/modules/queue';
import { debounce } from 'lodash-es';
import { storeToRefs } from 'pinia';
import { computed, onMounted, onUnmounted } from 'vue';

const metricsStore = useMetricsStore();
const analyticsStore = useAnalyticsStore();
const historyStore = useHistoryStore();
const queueStore = useQueueStore();
const { nowTime, uptime } = storeToRefs(metricsStore);
const { currentFilters } = storeToRefs(analyticsStore);
const { fetchMetrics, initializeTimers, cleanupTimers } = metricsStore;
const { fetchAnalytics } = analyticsStore;
const { fetchHistory } = historyStore;
const { fetchQueue } = queueStore;

const { color } = useTheme();
const isDarkMode = computed(() => color.value === 'dark');

const { isMobile, isTablet } = useDevice();

onMounted(() => {
  initializeTimers();
});

onUnmounted(() => {
  cleanupTimers();
});

// Original refresh function without throttling
const performRefresh = (): void => {
  fetchMetrics();
  fetchAnalytics(
    currentFilters.value.selectedTime,
    currentFilters.value.selectedApi,
    currentFilters.value.selectedKey
  );
  fetchHistory();
  fetchQueue();
};

// Throttled refresh function - prevents rapid successive calls
const handleRefresh = debounce(performRefresh, 500);
</script>

<template>
  <div
    class="fixtool-container"
    :class="isMobile ? 'mobile-layout' : isTablet ? 'tablet-layout' : 'desktop-layout'"
  >
    <div
      class="time-display"
      :class="
        isMobile
          ? 'flex flex-col gap-2 px-2 text-sm'
          : 'flex items-center gap-2 px-2 text-sm md:text-base'
      "
    >
      <div
        class="uptime px-2 py-1 rounded-md"
        :class="isDarkMode ? 'bg-green-900 text-green-100' : 'bg-green-100 text-green-800'"
      >
        <span class="font-medium">Uptime:</span>
        <span class="ml-1">{{ uptime }}</span>
      </div>
      <div
        class="now-time px-2 py-1 rounded-md"
        :class="isDarkMode ? 'bg-blue-900 text-blue-100' : 'bg-blue-100 text-blue-800'"
      >
        <span>{{ nowTime }}</span>
      </div>
    </div>
    <el-button
      :class="isMobile ? 'refresh-button-mobile self-center' : 'refresh-button'"
      icon="Refresh"
      circle
      @click="handleRefresh"
    />
  </div>
</template>

<style scoped>
.fixtool-container {
  display: flex;
  align-items: center;
  gap: 4px;
}

.desktop-layout,
.tablet-layout {
  flex-direction: row;
}

.mobile-layout {
  width: 100%;
  flex-direction: row;
  justify-content: space-around;
}

.refresh-button-mobile {
  margin-left: auto;
  margin-right: 5px;
}

/* Add smooth transition for theme switching */
.uptime,
.now-time {
  transition:
    background-color 0.3s ease,
    color 0.3s ease;
}
</style>
