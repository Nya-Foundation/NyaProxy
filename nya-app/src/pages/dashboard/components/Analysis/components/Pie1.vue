<script setup lang="ts">
import { useECharts } from '@/hooks/useECharts';
import { useAnalyticsStore } from '@/stores/modules/analytics';
import type { Ref } from 'vue';
import { useTemplateRef, watchEffect } from 'vue';

const pie1Ref = useTemplateRef<HTMLDivElement | null>('pie1Ref');

const { setOptions } = useECharts(pie1Ref as Ref<HTMLDivElement>);

const analyticsStore = useAnalyticsStore();

watchEffect(() => {
  const data = analyticsStore.dataAnalytics;

  if (!data || !data.key_distribution) return;

  const pieData = Object.entries(data.key_distribution).map(([name, value]) => ({
    name,
    value: Number(value)
  }));

  setOptions(
    {
      tooltip: {
        trigger: 'item'
      },
      legend: {
        orient: 'vertical',
        left: 'right'
      },
      series: [
        {
          type: 'pie',
          radius: '50%',
          data: pieData,
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowOffsetX: 0,
              shadowColor: 'rgba(0, 0, 0, 0.5)'
            }
          }
        }
      ]
    },
    false
  );
});
</script>

<template>
  <div ref="pie1Ref" class="pie1-ref"></div>
</template>

<style lang="scss" scoped>
.pie1-ref {
  width: 100%;
  height: 320px;
}
</style>
