<script setup lang="ts">
import { useECharts } from '@/hooks/useECharts';
import { useAnalyticsStore } from '@/stores/modules/analytics';
import type { Ref } from 'vue';
import { useTemplateRef, watchEffect } from 'vue';

const line1Ref = useTemplateRef<HTMLDivElement | null>('line1Ref');

const { setOptions } = useECharts(line1Ref as Ref<HTMLDivElement>);

const analyticsStore = useAnalyticsStore();

watchEffect(() => {
  const data = analyticsStore.dataAnalytics;
  if (!data || data.length === 0) return;

  setOptions(
    {
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'cross',
          label: {
            backgroundColor: '#6a7985'
          }
        }
      },
      legend: {
        data: ['Requests', 'Errors']
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        containLabel: true
      },
      xAxis: [
        {
          type: 'category',
          boundaryGap: false,
          data: analyticsStore.dataAnalytics.time_intervals || [],
          splitLine: {
            show: true,
            lineStyle: {
              type: 'dashed',
              color: '#ccc'
            }
          }
        }
      ],
      yAxis: [
        {
          type: 'value'
        }
      ],
      series: [
        {
          name: 'Requests',
          type: 'line',
          smooth: false,
          symbol: 'circle',
          symbolSize: 6,
          itemStyle: {
            color: '#3b82f6'
          },
          emphasis: {
            focus: 'series'
          },
          data: analyticsStore.dataAnalytics.requests_over_time || []
        },
        {
          name: 'Errors',
          type: 'line',
          smooth: false,
          symbol: 'circle',
          symbolSize: 6,
          itemStyle: {
            color: '#ef4444'
          },
          emphasis: {
            focus: 'series'
          },
          data: analyticsStore.dataAnalytics.errors_over_time || []
        }
      ]
    },
    false
  );
});
</script>

<template>
  <div ref="line1Ref" class="line1-ref"></div>
</template>

<style lang="scss" scoped>
.line1-ref {
  width: 100%;
  height: 320px;
}
</style>
