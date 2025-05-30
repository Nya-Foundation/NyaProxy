import { getQuene } from '@/api/dashboardApi';
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';

export const useQueueStore = defineStore('queue', () => {
  const queueData = ref<any>(null);

  const fetchQueue = async (): Promise<void> => {
    try {
      const res = await getQuene();
      queueData.value = res;
    } catch (error) {
      console.error('Failed to fetch queue:', error);
    }
  };

  const dataQueue = computed(() => queueData.value ?? {});

  return {
    queueData,
    fetchQueue,
    dataQueue
  };
});