import type { AppConfig } from '@/types/appConfig';
import { updateColor } from '@/utils/transformTheme';
import { useColorMode } from '@vueuse/core';
import { watch } from 'vue';
import { useAppSettings } from './useAppSetting';

export const useTheme = () => {
  const color = useColorMode({ disableTransition: false });

  const { appConfig, setAppConfigMode } = useAppSettings();

  const toggleDarkMode = () => {
    setAppConfigMode({ themeMode: color.value as AppConfig['themeMode'] });
  };

  watch(color, () => {
    toggleDarkMode();
    updateColor(appConfig.value.primaryColor, color.value as AppConfig['themeMode']);
  });

  return { color };
};
