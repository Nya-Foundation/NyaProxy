import { getMetrics } from '@/api/index';
import dayjs from 'dayjs';
import { defineStore } from 'pinia';
import { computed, ref, shallowRef } from 'vue';

export const useMetricsStore = defineStore('metrics', () => {
  const initTime = shallowRef<dayjs.Dayjs | null>(null);
  const initialUptime = ref<number>(0);
  const nowTime = ref<string>(dayjs().format('YYYY-MM-DD HH:mm:ss'));
  const uptime = ref<string>('00:00:00:00');

  const metricsData = ref<any>(null);

  let timer: number | undefined;

  const formatUptime = (seconds: number): string => {
    const days = Math.floor(seconds / (3600 * 24));
    const hours = Math.floor((seconds % (3600 * 24)) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    const formattedDays = days < 100 ? days.toString().padStart(2, '0') : days.toString();

    return `${formattedDays}:${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  const updateTimeDisplay = (): void => {
    nowTime.value = dayjs().format('YYYY-MM-DD HH:mm:ss');

    if (initTime.value && initialUptime.value) {
      const elapsedSeconds = dayjs().diff(initTime.value, 'second');
      const currentUptime = initialUptime.value + elapsedSeconds;
      uptime.value = formatUptime(currentUptime);
    }
  };

  const fetchMetrics = async (): Promise<void> => {
    try {
      const res = await getMetrics();
      metricsData.value = res;

      if (res?.global?.uptime_seconds && !initTime.value) {
        initialUptime.value = res.global.uptime_seconds;
        initTime.value = dayjs();
        uptime.value = formatUptime(initialUptime.value);
      }
    } catch (error) {
      console.error('Failed to fetch metrics:', error);
    }
  };

  const initializeTimers = (): void => {
    fetchMetrics();
    updateTimeDisplay();
    timer = window.setInterval(updateTimeDisplay, 1000);
  };

  const cleanupTimers = (): void => {
    timer && clearInterval(timer);
  };

  const dataList = computed((): Array<{title: string, value: number}> => [
    {
      title: 'Total Requests',
      value: metricsData.value?.global?.total_requests ?? 0
    },
    {
      title: 'Total Errors',
      value: metricsData.value?.global?.total_errors ?? 0
    },
    {
      title: 'Rate Limit Hits',
      value: metricsData.value?.global?.total_rate_limit_hits ?? 0
    },
    {
      title: 'Queue Hits',
      value: metricsData.value?.global?.total_queue_hits ?? 0
    }
  ]);

  return {
    nowTime,
    uptime,
    metricsData,

    fetchMetrics,
    initializeTimers,
    cleanupTimers,

    dataList
  };
});
