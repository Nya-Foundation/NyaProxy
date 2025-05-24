import type { AppConfig } from '@/types/appConfig';
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';

export const useAppStore = defineStore('app', () => {
  const AppState = ref<AppConfig>({} as AppConfig);
  function setAppConfig(data: AppConfig) {
    const newData = data;
    localStorage.setItem('appConfig', JSON.stringify(newData));
    AppState.value = newData;
  }

  const getAppConfig = computed((): AppConfig => AppState.value);

  return {
    AppState,
    getAppConfig,
    setAppConfig
  };
});
