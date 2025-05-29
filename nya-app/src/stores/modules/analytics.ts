import { getAnalytics } from '@/api';
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';

export interface AnalyticsFilters {
  selectedTime: string;
  selectedApi: string;
  selectedKey: string;
}

export const useAnalyticsStore = defineStore('analytics', () => {
  const analyticsData = ref<any>(null);

  // Store current filter selections
  const filters = ref<AnalyticsFilters>({
    selectedTime: '24h',
    selectedApi: '',
    selectedKey: ''
  });

  const fetchAnalytics = async (
    time: string,
    api_name?: string,
    key_id?: string
  ): Promise<void> => {
    try {
      const res = await getAnalytics(time, api_name, key_id);
      analyticsData.value = res;
    } catch (error) {
      console.error('Failed to fetch analytics:', error);
    }
  };

  // Update filters and trigger refresh
  const updateFilters = (newFilters: Partial<AnalyticsFilters>): void => {
    filters.value = { ...filters.value, ...newFilters };
    // Auto fetch analytics when filters change
    fetchAnalytics(
      filters.value.selectedTime,
      filters.value.selectedApi,
      filters.value.selectedKey
    );
  };

  // Computed getter for analytics data
  const dataAnalytics = computed(() => {
    return analyticsData.value?.data ?? [];
  });

  // Computed getter for current filters
  const currentFilters = computed(() => filters.value);

  return {
    analyticsData,
    filters,
    fetchAnalytics,
    updateFilters,
    dataAnalytics,
    currentFilters
  };
});
