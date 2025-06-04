<script setup lang="ts">
import { useECharts } from '@/hooks/useECharts';
import { useAnalyticsStore } from '@/stores/modules/analytics';
import type { Ref } from 'vue';
import { useTemplateRef, watchEffect } from 'vue';

const line2Ref = useTemplateRef<HTMLDivElement | null>('line2Ref');

const { setOptions } = useECharts(line2Ref as Ref<HTMLDivElement>);

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
        data: ['Average Response Time (ms)']
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
          type: 'value',
          axisLabel: {
            formatter: '{value} ms'
          }
        }
      ],
      series: [
        {
          name: 'Average Response Time (ms)',
          type: 'line',
          smooth: false,
          symbol: 'circle',
          symbolSize: 6,
          emphasis: {
            focus: 'series'
          },
          data: analyticsStore.dataAnalytics.avg_response_times || []
        }
      ]
    },
    false
  );
});
</script>

<template>
  <div ref="line2Ref" class="line2-ref"></div>
</template>

<style lang="scss" scoped>
.line2-ref {
  width: 100%;
  height: 320px;
}
</style>
