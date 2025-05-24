import { useAppStore } from '@/stores/modules/app';
import type { AppConfig } from '@/types/appConfig';
import { merge } from 'lodash-es';
import { storeToRefs } from 'pinia';

export function useAppSettings() {
  const appStore = useAppStore();
  const { AppState } = storeToRefs(appStore);

  function setAppConfigMode(config: Partial<AppConfig>) {
    appStore.setAppConfig(merge(appStore.AppState, config));
  }

  return { appConfig: AppState, setAppConfigMode };
}