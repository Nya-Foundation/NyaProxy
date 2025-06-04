<script setup lang="ts">
import { useECharts } from '@/hooks/useECharts';
import { useAnalyticsStore } from '@/stores/modules/analytics';
import type { Ref } from 'vue';
import { useTemplateRef, watchEffect } from 'vue';

const barRef = useTemplateRef<HTMLDivElement | null>('barRef');

const { setOptions } = useECharts(barRef as Ref<HTMLDivElement>);

const analyticsStore = useAnalyticsStore();

watchEffect(() => {
  const data = analyticsStore.dataAnalytics;
  const dist = data?.api_distribution || {};
  const xData = Object.keys(dist);
  const yData = Object.values(dist) as number[];

  if (xData.length === 0) return;

  // Generate color palette for different bars
  const colorPalette = [
    '#5470C6',
    '#91CC75',
    '#FAC858',
    '#EE6666',
    '#73C0DE',
    '#3BA272',
    '#FC8452',
    '#9A60B4',
    '#EA7CCC',
    '#FFC300',
    '#FF6B6B',
    '#4ECDC4',
    '#45B7D1',
    '#96CEB4',
    '#FFEAA7'
  ];

  // Create data with individual colors for each bar
  const seriesData = yData.map((value, index) => ({
    value,
    itemStyle: {
      color: colorPalette[index % colorPalette.length]
    }
  }));

  setOptions(
    {
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'shadow'
        }
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
          data: xData,
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
          name: 'API Requests',
          type: 'bar',
          barWidth: '60%',
          data: seriesData
        }
      ]
    },
    false
  );
});
</script>

<template>
  <div ref="barRef" class="bar-ref"></div>
</template>

<style lang="scss" scoped>
.bar-ref {
  width: 100%;
  height: 320px;
}
</style>
