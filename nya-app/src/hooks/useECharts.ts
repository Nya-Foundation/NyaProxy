// echarts
import { BarChart, LineChart, PieChart } from 'echarts/charts';
import {
    GridComponent,
    LegendComponent,
    TitleComponent,
    TooltipComponent
} from 'echarts/components';
import * as echarts from 'echarts/core';
import { LabelLayout, UniversalTransition } from 'echarts/features';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  LineChart,
  BarChart,
  PieChart,
  LabelLayout,
  CanvasRenderer,
  UniversalTransition
]);

// another
import { useAppSettings } from '@/hooks/useAppSetting';
import { useEventListener } from '@/hooks/useEventListener';
import { tryOnUnmounted, useDebounceFn } from '@vueuse/core';
import type { EChartsOption } from 'echarts';
import type { Ref } from 'vue';
import { nextTick, ref, unref, watch } from 'vue';

export type createEchartsOption = EChartsOption;

export function useECharts(elRef: Ref<HTMLDivElement>) {
  let chartInstance: echarts.ECharts | null = null;
  const cacheOptions = ref({}) as Ref<EChartsOption>;
  let resizeFn: Fn = resize;
  let removeResizeFn: Fn = () => {};

  // Get app settings for theme detection
  const { appConfig } = useAppSettings();

  resizeFn = useDebounceFn(resize, 200);

  // Create echarts with dynamic theme
  function initCharts(theme?: string) {
    const el = unref(elRef);
    if (!el || !unref(el)) return;

    // Dispose existing instance if exists
    if (chartInstance) {
      chartInstance.dispose();
      chartInstance = null;
    }

    // Use theme based on app config, fallback to light
    const currentTheme = theme ?? appConfig.value?.themeMode ?? 'light';
    chartInstance = echarts.init(el, currentTheme);

    const { removeEvent } = useEventListener({
      el: window,
      name: 'resize',
      listener: resizeFn
    });
    removeResizeFn = removeEvent;
  }

  // Watch for theme changes and reinitialize chart
  watch(
    () => appConfig.value?.themeMode,
    (newTheme) => {
      if (chartInstance && newTheme) {
        // Reinitialize with new theme
        initCharts(newTheme);
        // Reapply cached options
        if (cacheOptions.value && Object.keys(cacheOptions.value).length > 0) {
          chartInstance?.setOption(unref(cacheOptions), true);
        }
      }
    },
    { immediate: false }
  );

  function setOptions(options: EChartsOption, clear = true) {
    // Merge transparent background and animation settings with user options
    const optionsWithEnhancements = {
      backgroundColor: 'transparent',
      animation: true,
      animationDuration: 1000,
      animationEasing: 'cubicOut' as const,
      ...options
    };
    cacheOptions.value = optionsWithEnhancements;
    nextTick(() => {
      if (!chartInstance) {
        initCharts();
        if (!chartInstance) return;
      }

      // For dynamic updates, don't clear the chart to maintain smooth transitions
      // Only clear when explicitly requested (for initial setup or major changes)
      if (clear) {
        chartInstance?.clear();
        chartInstance?.setOption(unref(cacheOptions), true);
      } else {
        // Use notMerge: false for smooth data updates without clearing
        chartInstance?.setOption(unref(cacheOptions), false);
      }
    });
  }

  function resize() {
    chartInstance?.resize();
  }

  tryOnUnmounted(() => {
    if (!chartInstance) return;
    removeResizeFn();
    chartInstance.dispose();
    chartInstance = null;
  });

  return {
    echarts,
    setOptions,
    resize
  };
}
