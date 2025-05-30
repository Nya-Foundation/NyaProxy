<script setup lang="ts">
import { useMetricsStore } from '@/stores/modules/metrics';

const metricsStore = useMetricsStore();
// Get card theme based on index
const getCardTheme = (index: number): string => {
  const themes = ['primary', 'danger', 'warning', 'purple'];
  return themes[index] || 'primary';
};
</script>

<template>
  <div class="global-statistics">
    <div class="main-header mb-2 px-2 py-1 flex items-center">
      <div class="title flex items-center text-lg md:text-xl">
        <el-icon color="var(--el-color-primary)"><Monitor /></el-icon>
        <span class="title-text ml-1">Global Statistics</span>
      </div>
    </div>
    <el-row class="enter-y" :gutter="20">
      <el-col
        v-for="(item, index) in metricsStore.dataList"
        :key="index"
        :xs="24"
        :sm="24"
        :md="6"
        :lg="6"
        :xl="6"
      >
        <el-card shadow="hover" :class="['metric-card', `metric-card--${getCardTheme(index)}`]">
          <div class="card-content">
            <div class="card-header">
              <span class="card-title">{{ item.title }}</span>
            </div>
            <div class="numerical-value">
              <span class="number">{{ item.value }}</span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped lang="scss">
.metric-card {
  margin-bottom: 20px;
  transition: all 0.3s ease;

  // Primary theme - blue
  &--primary {
    --card-accent-color: #409eff;
    --card-bg-light: rgba(64, 158, 255, 0.05);
  }

  // Danger theme - red
  &--danger {
    --card-accent-color: #f56c6c;
    --card-bg-light: rgba(245, 108, 108, 0.05);
  }

  // Warning theme - yellow
  &--warning {
    --card-accent-color: #e6a23c;
    --card-bg-light: rgba(230, 162, 60, 0.05);
  }

  // Purple theme - light purple
  &--purple {
    --card-accent-color: #9c88ff;
    --card-bg-light: rgba(156, 136, 255, 0.05);
  }

  :deep(.el-card__body) {
    background: var(--card-bg-light);
  }

  .card-content {
    .card-header {
      margin-bottom: 16px;

      .card-title {
        font-size: 14px;
        font-weight: 500;
        color: var(--el-text-color-regular);
      }
    }

    .numerical-value {
      display: flex;
      align-items: center;

      .number {
        font-size: 28px;
        font-weight: 600;
        color: var(--card-accent-color);
        line-height: 1;
      }
    }
  }
}
</style>
