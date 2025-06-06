<script setup lang="ts">
import { useECharts } from '@/hooks/useECharts';
import { useAnalyticsStore } from '@/stores/modules/analytics';
import type { Ref } from 'vue';
import { useTemplateRef, watchEffect } from 'vue';

const pie2Ref = useTemplateRef<HTMLDivElement | null>('pie2Ref');

const { setOptions } = useECharts(pie2Ref as Ref<HTMLDivElement>);

const analyticsStore = useAnalyticsStore();

watchEffect(() => {
  const data = analyticsStore.dataAnalytics;

  if (!data || data.length === 0) return;

  // Define color mapping for status codes
  const getColorForStatusCode = (statusCode: string): string => {
    if (statusCode === '200') {
      return '#90EE90'; // Light green for status code 200
    }
    // Return default colors for other status codes
    const colorMap: Record<string, string> = {
      '400': '#E74C3C', // Bad Request - Red
      '401': '#F39C12', // Unauthorized - Orange
      '402': '#D68910', // Payment Required - Golden
      '403': '#FFA502', // Forbidden - Orange
      '404': '#FF6B6B', // Not Found - Light Red
      '405': '#DC7633', // Method Not Allowed - Brown Orange
      '408': '#AF7AC5', // Request Timeout - Light Purple
      '409': '#C0392B', // Conflict - Dark Red
      '410': '#922B21', // Gone - Dark Red
      '422': '#B7950B', // Unprocessable Entity - Dark Yellow
      '429': '#8E44AD', // Too Many Requests - Purple
      '500': '#FF4757', // Internal Server Error - Bright Red
      '501': '#CB4335', // Not Implemented - Red
      '502': '#A93226', // Bad Gateway - Dark Red
      '503': '#7D3C98', // Service Unavailable - Purple
      '504': '#6C3483', // Gateway Timeout - Dark Purple
      '301': '#3742FA', // Moved Permanently - Blue
      '302': '#5352ED', // Found - Purple Blue
      '307': '#2E86AB', // Temporary Redirect - Dark Blue
      '308': '#1B4F72' // Permanent Redirect - Navy Blue
    };
    return colorMap[statusCode] || '#70A1FF'; // Default blue for unknown status codes
  };

  const pieData = Object.entries(data.status_code_distribution).map(([name, value]) => ({
    name,
    value: Number(value),
    itemStyle: {
      color: getColorForStatusCode(name),
      borderRadius: 10,
      borderColor: '#fff',
      borderWidth: 2
    }
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
          radius: ['45%', '70%'],
          avoidLabelOverlap: false,
          data: pieData,
          label: {
            show: true,
            position: 'outside'
          },
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
  <div ref="pie2Ref" class="pie2-ref"></div>
</template>

<style lang="scss" scoped>
.pie2-ref {
  width: 100%;
  height: 320px;
}
</style>
