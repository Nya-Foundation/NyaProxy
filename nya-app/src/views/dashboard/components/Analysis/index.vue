<script setup lang="ts">
import { useAnalyticsStore } from '@/stores/modules/analytics';
import { storeToRefs } from 'pinia';
import { computed } from 'vue';
import Bar from './components/Bar.vue';
import Line1 from './components/Line1.vue';
import Line2 from './components/Line2.vue';
import Pie1 from './components/Pie1.vue';
import Pie2 from './components/Pie2.vue';

const analyticsStore = useAnalyticsStore();
const { filters } = storeToRefs(analyticsStore);
const { updateFilters } = analyticsStore;

// Use computed properties to sync with store
const selectedTime = computed({
  get: () => filters.value.selectedTime,
  set: (value: string) => updateFilters({ selectedTime: value })
});

const selectedApi = computed({
  get: () => filters.value.selectedApi,
  set: (value: string) => updateFilters({ selectedApi: value })
});

const selectedKey = computed({
  get: () => filters.value.selectedKey,
  set: (value: string) => updateFilters({ selectedKey: value })
});
</script>

<template>
  <div class="analytics-container">
    <!-- Title section - outside of main container -->
    <div class="title-section mb-2 px-2 py-1 flex items-center text-lg md:text-xl">
      <el-icon class="title-icon"><TrendCharts /></el-icon>
      <span class="title-text ml-1">Analytics</span>
    </div>

    <!-- Main content container using el-card -->
    <el-card shadow="hover" class="main-content-card">
      <!-- Enhanced filters section -->
      <div class="filters-section">
        <div class="filters-header">
          <el-icon class="filters-icon"><Filter /></el-icon>
          <span class="filters-title">Filters</span>
        </div>

        <div class="filters-controls">
          <div class="filter-group">
            <label class="filter-label" for="api-select">API Selection</label>
            <el-select
              id="api-select"
              v-model="selectedApi"
              placeholder="All APIs"
              class="filter-select"
              clearable
            >
              <el-option label="All APIs" value="" />
              <el-option
                v-for="api in analyticsStore.analyticsData?.filters?.apis || []"
                :key="api"
                :label="api"
                :value="api"
              />
            </el-select>
          </div>

          <div class="filter-group">
            <label class="filter-label" for="key-select">API Key</label>
            <el-select
              id="key-select"
              v-model="selectedKey"
              placeholder="All Keys"
              class="filter-select"
              clearable
            >
              <el-option label="All Keys" value="" />
              <el-option
                v-for="key in analyticsStore.analyticsData?.filters?.keys || []"
                :key="key"
                :label="key"
                :value="key"
              />
            </el-select>
          </div>

          <div class="filter-group">
            <label class="filter-label" for="time-select">Time Range</label>
            <el-select
              id="time-select"
              v-model="selectedTime"
              placeholder="Time Range"
              class="filter-select"
            >
              <el-option label="Last Hour" value="1h" />
              <el-option label="Last 24 Hours" value="24h" />
              <el-option label="Last 7 Days" value="7d" />
              <el-option label="Last 30 Days" value="30d" />
              <el-option label="All Time" value="all" />
            </el-select>
          </div>
        </div>
      </div>

      <!-- Charts section -->
      <div class="charts-section">
        <div class="charts-header">
          <el-icon class="charts-icon"><DataAnalysis /></el-icon>
          <span class="charts-title">Data Visualization</span>
        </div>
        <el-row :gutter="20" class="enter-y">
          <el-col :xs="24" :sm="24" :md="12" :lg="12" :xl="12">
            <el-card shadow="hover" class="box-card">
              <template #header>
                <div class="card-header cursor">
                  <span>API Traffic Overview</span>
                </div>
              </template>
              <Line1 />
            </el-card>
          </el-col>
          <el-col :xs="24" :sm="24" :md="12" :lg="12" :xl="12">
            <el-card shadow="hover" class="box-card">
              <template #header>
                <div class="card-header cursor">
                  <span>Response Time Analysis</span>
                </div>
              </template>
              <Line2 />
            </el-card>
          </el-col>
        </el-row>

        <el-row :gutter="20" class="enter-y">
          <el-col :xs="24" :sm="24" :md="8" :lg="8" :xl="8">
            <el-card shadow="hover" class="box-card">
              <template #header>
                <div class="card-header cursor">
                  <span>API Usage Distribution</span>
                </div>
              </template>
              <Bar />
            </el-card>
          </el-col>
          <el-col :xs="24" :sm="12" :md="8" :lg="8" :xl="8">
            <el-card shadow="hover" class="box-card">
              <template #header>
                <div class="card-header cursor">
                  <span>API Key Usage</span>
                </div>
              </template>
              <Pie1 />
            </el-card>
          </el-col>
          <el-col :xs="24" :sm="12" :md="8" :lg="8" :xl="8">
            <el-card shadow="hover" class="box-card">
              <template #header>
                <div class="card-header cursor">
                  <span>Status Code Distribution</span>
                </div>
              </template>
              <Pie2 />
            </el-card>
          </el-col>
        </el-row>
      </div>
    </el-card>
  </div>
</template>

<style scoped lang="scss">
.analytics-container {
  display: flex;
  flex-direction: column;

  .title-section {
    display: flex;
    align-items: center;

    .title-icon {
      color: var(--el-color-primary);
      transition: color 0.3s ease;
    }

    .title-text {
      transition: color 0.3s ease;
    }
  }

  .main-content-card {
    transition: all 0.3s ease;
  }

  .filters-section {
    margin-bottom: 2rem;

    .filters-header {
      display: flex;
      align-items: center;
      margin-bottom: 1rem;
      padding-bottom: 0.75rem;
      border-bottom: 2px solid var(--el-border-color-lighter);

      .filters-icon {
        margin-right: 0.5rem;
        font-size: 1.125rem;
        color: var(--el-color-primary);
        transition: color 0.3s ease;
      }

      .filters-title {
        font-weight: 500;
        font-size: 1rem;
        color: var(--el-text-color-primary);
        transition: color 0.3s ease;
      }
    }

    .filters-controls {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 1rem;

      @media (max-width: 768px) {
        grid-template-columns: 1fr;
      }

      .filter-group {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;

        .filter-label {
          display: block;
          font-size: 0.875rem;
          font-weight: 500;
          margin-bottom: 0.5rem;
          color: var(--el-text-color-regular);
          transition: color 0.3s ease;
        }

        .filter-select {
          width: 100%;

          :deep(.el-select__wrapper) {
            border-radius: 6px;
            transition: all 0.3s ease;
            background: var(--el-fill-color-blank);
            border-color: var(--el-border-color);

            &:hover {
              border-color: var(--el-color-primary-light-3);
            }

            &.is-focused {
              border-color: var(--el-color-primary);
            }
          }

          :deep(.el-select__placeholder) {
            color: var(--el-text-color-placeholder);
            transition: color 0.3s ease;
          }

          :deep(.el-input__inner) {
            color: var(--el-text-color-primary);
            transition: color 0.3s ease;
          }
        }
      }
    }
  }

  .charts-section {
    .charts-header {
      display: flex;
      align-items: center;
      margin-bottom: 1rem;
      padding-bottom: 0.75rem;
      border-bottom: 2px solid var(--el-border-color-lighter);

      .charts-icon {
        margin-right: 0.5rem;
        font-size: 1.125rem;
        color: var(--el-color-primary);
        transition: color 0.3s ease;
      }

      .charts-title {
        font-weight: 500;
        font-size: 1rem;
        color: var(--el-text-color-primary);
        transition: color 0.3s ease;
      }
    }

    .enter-y {
      margin-bottom: 1.25rem;

      &:last-child {
        margin-bottom: 0;
      }
    }
  }
}

.box-card {
  margin-bottom: 20px;
  border-radius: 6px;
  transition: all 0.3s ease;
  background: var(--el-bg-color);
  border-color: var(--el-border-color-light);

  :deep(.el-card__header) {
    padding: 16px 20px 12px;
    border: none;
    background: linear-gradient(
      135deg,
      var(--el-fill-color-light) 0%,
      var(--el-fill-color-blank) 100%
    );
    border-radius: 6px 6px 0 0;
  }

  :deep(.el-card__body) {
    padding: 20px;
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-weight: 600;
    color: var(--el-text-color-primary);
    font-size: 0.95rem;
    transition: color 0.3s ease;
  }

  .card-content {
    :deep(.el-progress-bar__outer) {
      height: 17px !important;
    }

    .numerical-value {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      margin-bottom: 10px;

      .number {
        color: var(--el-text-color-primary);
        font-size: var(--el-font-size-extra-large);
        font-weight: 600;
        transition: color 0.3s ease;
      }
    }
  }
}

// Light mode specific styles
html.light {
  .analytics-container {
    .title-section {
      .title-icon {
        color: #409EFF;
      }

      .title-text {
        color: #303133;
      }
    }

    .main-content-card {
      background: #ffffff;
    }

    .filters-section {
      .filters-header {
        border-bottom-color: #E4E7ED;

        .filters-icon {
          color: #409EFF;
        }

        .filters-title {
          color: #303133;
        }
      }

      .filter-group {
        .filter-label {
          color: #606266;
        }

        .filter-select {
          :deep(.el-select__wrapper) {
            background: #F5F7FA;
            border-color: #DCDFE6;

            &:hover {
              border-color: #C0C4CC;
              background: #FAFAFA;
            }

            &.is-focused {
              background: #FFFFFF;
            }
          }
        }
      }
    }

    .charts-section {
      .charts-header {
        border-bottom-color: #E4E7ED;

        .charts-icon {
          color: #409EFF;
        }

        .charts-title {
          color: #303133;
        }
      }
    }
  }

  .box-card {
    background: #FFFFFF;
    border-color: #EBEEF5;

    &:hover {
      border-color: #C0C4CC;
      box-shadow:
        0 12px 20px -4px rgba(0, 0, 0, 0.08),
        0 6px 8px -2px rgba(0, 0, 0, 0.04);
    }

    :deep(.el-card__header) {
      background: linear-gradient(
        135deg,
        #F5F7FA 0%,
        #FAFBFC 100%
      );
      border-bottom: 1px solid #EBEEF5;
    }

    .card-header {
      color: #303133;
    }
  }
}

// Dark mode enhancements
html.dark {
  .analytics-container {
    .main-content-card {
      background: var(--el-bg-color-page);
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    }

    .filters-section {
      .filters-header {
        border-bottom-color: var(--el-border-color);
      }
    }

    .charts-section {
      .charts-header {
        border-bottom-color: var(--el-border-color);
      }
    }
  }

  .box-card {
    background: var(--el-bg-color);
    border-color: var(--el-border-color);

    &:hover {
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    }

    :deep(.el-card__header) {
      background: linear-gradient(135deg, var(--el-fill-color) 0%, var(--el-fill-color-light) 100%);
    }
  }
}

// Responsive design
@media (max-width: 1024px) {
  .analytics-container {
    .main-content-card {
      :deep(.el-card__body) {
        padding: 1rem;
      }
    }

    .title-section {
      margin-bottom: 1rem;

      .title-text {
        font-size: 1.25rem;
      }
    }
  }
}

@media (max-width: 768px) {
  .analytics-container {
    .filters-section {
      .filters-controls {
        grid-template-columns: 1fr;
        gap: 1rem;
      }
    }
  }
}
</style>
