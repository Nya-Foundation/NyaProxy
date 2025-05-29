import { getHistory } from '@/api';
import dayjs from 'dayjs';
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';

export const useHistoryStore = defineStore('history', () => {
  const historyData = ref<any>(null);

  const fetchHistory = async (): Promise<void> => {
    try {
      const res = await getHistory();
      historyData.value = res;
    } catch (error) {
      console.error('Failed to fetch history:', error);
    }
  };

  const dataHistory = computed(() => {
    const raw = historyData.value?.history ?? [];
    return raw
      .sort((a: any, b: any) => b.timestamp - a.timestamp)
      .map((item: any) => ({
        time: dayjs(item.timestamp * 1000).format('YYYY-MM-DD HH:mm:ss'),
        apiName: item.api_name,
        status: item.status_code,
        ResponseTime: formatElapsed(item.elapsed_ms),
        apiKey: item.key_id
      }));
  });

  const formatElapsed = (ms: number): string => {
    if (ms < 1000) return `${ms.toFixed(1)} ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
    return `${(ms / 60000).toFixed(1)} min`;
  };

  return {
    historyData,
    fetchHistory,
    dataHistory
  };
});
