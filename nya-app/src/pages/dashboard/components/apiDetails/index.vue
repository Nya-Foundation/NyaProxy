<script setup lang="ts">
import { useDevice } from '@/hooks/useDevice';
import { useMetricsStore } from '@/stores/modules/metrics';
import { ElMessage } from 'element-plus';
import { computed, ref } from 'vue';

const metricsStore = useMetricsStore();

const searchQuery = ref('');

const dialogVisible = ref(false);
const selectedApi = ref<any>(null);

const { isMobile, isTablet } = useDevice();

// Computed property to transform APIs data into table format
const tableData = computed(() => {
  const apis = metricsStore.metricsData?.apis || {};

  return Object.entries(apis)
    .map(([apiName, apiData]: [string, any]) => {
      return {
        name: apiName,
        requests: apiData.requests || 0,
        errors: apiData.errors || 0,
        avgResponseTime: apiData.avg_response_time_ms
          ? `${(apiData.avg_response_time_ms / 1000).toFixed(2)}s`
          : '0s',
        lastRequest: apiData.last_request_time
          ? formatLastRequestTime(apiData.last_request_time)
          : 'Never',
        rawData: apiData // Store raw data for details modal
      };
    })
    .filter(api => api.name.toLowerCase().includes(searchQuery.value.toLowerCase()));
});

// Format last request time to relative time
const formatLastRequestTime = (timestamp: number): string => {
  const now = Date.now() / 1000;
  const diff = now - timestamp;

  if (diff < 60) return 'Just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

// Handle view details action
const handleViewDetails = (row: any) => {
  selectedApi.value = row;
  dialogVisible.value = true;
};

// Handle copy API link action
const handleCopyApiLink = async (row: any) => {
  const apiLink = window.location.origin + '/api/' + encodeURIComponent(row.name);

  try {
    await navigator.clipboard.writeText(apiLink);

    // Show success message
    ElMessage({
      message: `API链接已复制到剪贴板: ${apiLink}`,
      type: 'success',
      duration: 3000
    });
  } catch (error) {
    console.error('Failed to copy to clipboard:', error);

    // Show error message if clipboard API is not available
    ElMessage({
      message: '复制失败，请手动复制链接',
      type: 'error',
      duration: 3000
    });
  }
};

// Computed properties for dialog data
const errorRate = computed(() => {
  if (!selectedApi.value) return { text: '0/0', percentage: '0%' };
  const { requests, errors } = selectedApi.value;
  const percentage = requests > 0 ? ((errors / requests) * 100).toFixed(1) : '0';
  return {
    text: `${errors}/${requests}`,
    percentage: `${percentage}%`
  };
});

const responseTimeStats = computed(() => {
  if (!selectedApi.value?.rawData) return null;
  const data = selectedApi.value.rawData;
  return {
    avg: data.avg_response_time_ms ? `${(data.avg_response_time_ms / 1000).toFixed(2)}s` : '0s',
    min: data.min_response_time_ms ? `${Math.round(data.min_response_time_ms)}ms` : '0ms',
    max: data.max_response_time_ms ? `${(data.max_response_time_ms / 1000).toFixed(2)}s` : '0s'
  };
});

const statusCodeDistribution = computed(() => {
  if (!selectedApi.value?.rawData?.responses) return [];
  const responses = selectedApi.value.rawData.responses;
  const totalRequests = selectedApi.value.requests;

  return Object.entries(responses).map(([code, count]: [string, any]) => ({
    code,
    count,
    percentage: totalRequests > 0 ? ((count / totalRequests) * 100).toFixed(1) : '0'
  }));
});

const apiKeyUsage = computed(() => {
  if (!selectedApi.value?.rawData?.key_usage) return [];
  return Object.entries(selectedApi.value.rawData.key_usage).map(([key, count]: [string, any]) => ({
    key,
    count
  }));
});

// Responsive layout helper functions
const getDialogWidth = (): string => {
  if (isMobile.value) return '95%';
  if (isTablet.value) return '90%';
  return '800px';
};

const getGutter = (): number => {
  if (isMobile.value) return 12;
  if (isTablet.value) return 16;
  return 20;
};

const getColSpan = (): number => {
  if (isMobile.value) return 24;
  return 12;
};

const getColClass = (index: number): string => {
  if (isMobile.value) {
    return index === 0 ? '' : 'mt-3';
  }
  return index >= 2 ? 'mt-4' : '';
};

const getTableColSpan = (): number => {
  if (isMobile.value) return 24;
  return 12;
};

const getTableSize = (): 'small' | 'default' | 'large' => {
  if (isMobile.value) return 'small';
  return 'default';
};
</script>

<template>
  <div class="mt-5">
    <!-- Header Section -->
    <div class="header-section mb-2 px-2 py-1 flex justify-between items-center">
      <div class="flex items-center text-lg md:text-xl">
        <el-icon color="var(--el-color-primary)">
          <Connection />
        </el-icon>
        <span class="ml-1">API Details</span>
      </div>
      <el-input
        v-model="searchQuery"
        placeholder="Search by API name..."
        class="search-input mt-2"
        clearable
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
    </div>

    <!-- Content Container -->
    <el-card shadow="hover">
      <!-- Table Section -->
      <div class="table-wrapper">
        <el-table :data="tableData" table-layout="auto" class="api-table">
          <el-table-column fixed prop="name" label="API NAME" min-width="120" />

          <el-table-column prop="requests" label="REQUESTS" min-width="120" />

          <el-table-column prop="errors" label="ERRORS" min-width="120">
            <template #default="{ row }">
              <span :class="{ 'error-text': row.errors > 0 }">
                {{ row.errors }}
              </span>
            </template>
          </el-table-column>

          <el-table-column prop="avgResponseTime" label="AVG RESPONSE TIME" min-width="120" />

          <el-table-column prop="lastRequest" label="LAST REQUEST" min-width="120">
            <template #default="{ row }">
              <span class="text-gray-500 text-sm">{{ row.lastRequest }}</span>
            </template>
          </el-table-column>

          <el-table-column label="ACTIONS" min-width="120" align="center">
            <template #default="{ row }">
              <div class="action-buttons">
                <el-button link type="warning" @click="handleCopyApiLink(row)">
                  Copy API Link
                </el-button>
                <el-button
                  style="margin-left: 4px"
                  link
                  type="primary"
                  @click="handleViewDetails(row)"
                >
                  View Details
                </el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- API Details Dialog -->
    <el-dialog
      v-model="dialogVisible"
      :width="getDialogWidth()"
      destroy-on-close
      class="api-details-dialog"
      :show-close="true"
      :close-on-click-modal="true"
      :close-on-press-escape="true"
    >
      <template #header>
        <div class="dialog-header">
          <h3 class="dialog-title">API - {{ selectedApi?.name || '' }}</h3>
        </div>
      </template>
      <el-divider class="title-divider" />
      <div class="dialog-content" v-if="selectedApi">
        <el-row :gutter="getGutter()">
          <!-- First Row: Total Requests and Error Rate -->
          <el-col :span="getColSpan()" :class="getColClass(0)">
            <el-card shadow="never" class="stat-card">
              <div class="stat-label">Total Requests</div>
              <div class="stat-value">{{ selectedApi.requests }}</div>
            </el-card>
          </el-col>
          <el-col :span="getColSpan()" :class="getColClass(1)">
            <el-card shadow="never" class="stat-card">
              <div class="stat-label">Error Rate</div>
              <div class="stat-value">
                {{ errorRate.percentage }}
                <span class="stat-detail">({{ errorRate.text }})</span>
              </div>
            </el-card>
          </el-col>

          <!-- Second Row: Response Time and Queue/Rate Limits -->
          <el-col :span="getColSpan()" :class="getColClass(2)">
            <el-card shadow="never" class="stat-card">
              <div class="stat-label">Avg Response Time</div>
              <div class="stat-value">{{ responseTimeStats?.avg || '0s' }}</div>
              <div class="stat-detail" v-if="responseTimeStats">
                Min: {{ responseTimeStats.min }} / Max: {{ responseTimeStats.max }}
              </div>
            </el-card>
          </el-col>
          <el-col :span="getColSpan()" :class="getColClass(3)">
            <el-card shadow="never" class="stat-card">
              <div class="stat-label">Queue & Rate Limits</div>
              <div class="stat-value">{{ selectedApi.rawData?.queue_hits || 0 }}</div>
              <div class="stat-detail">
                Rate Limit Hits: {{ selectedApi.rawData?.rate_limit_hits || 0 }}
              </div>
            </el-card>
          </el-col>
        </el-row>

        <!-- Status Code Distribution and API Key Usage with Cards -->
        <el-row :gutter="getGutter()" class="mt-6">
          <!-- Status Code Distribution -->
          <el-col :span="getTableColSpan()" v-if="statusCodeDistribution.length > 0">
            <h4 class="section-title">Status Code Distribution</h4>
            <el-card shadow="never" class="data-card">
              <el-table :data="statusCodeDistribution" :size="getTableSize()" table-layout="auto">
                <el-table-column prop="code" label="Status Code">
                  <template #default="{ row }">
                    <el-tag
                      :type="
                        row.code === '200'
                          ? 'success'
                          : row.code.startsWith('4')
                            ? 'warning'
                            : 'danger'
                      "
                      size="small"
                    >
                      {{ row.code }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="Requests" align="right">
                  <template #default="{ row }"> {{ row.count }} requests </template>
                </el-table-column>
                <el-table-column prop="percentage" label="Percentage" align="right">
                  <template #default="{ row }"> {{ row.percentage }}% </template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>

          <!-- API Key Usage -->
          <el-col
            :span="isMobile ? 24 : 12"
            v-if="apiKeyUsage.length > 0"
            :class="isMobile ? 'mt-4' : ''"
          >
            <h4 class="section-title">API Key Usage</h4>
            <el-card shadow="never" class="data-card">
              <el-table :data="apiKeyUsage" :size="getTableSize()" table-layout="auto">
                <el-table-column prop="key" label="API Key" />
                <el-table-column label="Requests" align="right">
                  <template #default="{ row }"> {{ row.count }} requests </template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>
        </el-row>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.header-section {
  .search-input {
    width: 220px;

    :deep(.el-input__wrapper) {
      border-radius: 6px;
      background: var(--el-bg-color);
      border: 1px solid var(--el-border-color-darker);
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
      transition: all 0.3s ease;

      &:hover {
        border-color: var(--el-color-primary-light-7);
        background: var(--el-bg-color-page);
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.12);
      }

      &.is-focus {
        border-color: var(--el-color-primary);
        background: var(--el-bg-color);
        box-shadow: 0 0 0 2px var(--el-color-primary-light-8);
      }
    }

    :deep(.el-input__prefix) {
      color: var(--el-text-color-secondary);
    }
  }
}

.table-wrapper {
  position: relative;

  .api-table {
    width: 100%;
    overflow: hidden;

    .error-text {
      color: var(--el-color-danger);
    }

    .action-buttons {
      display: flex;
      flex-direction: column;
      gap: 4px;
      align-items: flex-start;

      @media (min-width: 768px) {
        flex-direction: row;
        gap: 8px;
        justify-content: center;
      }
    }
  }
}

// Dialog styles
.api-details-dialog {
  :deep(.el-dialog__header) {
    border-bottom: none;
  }

  .dialog-header {
    text-align: left;

    .dialog-title {
      margin: 0;
      font-size: 18px;
      font-weight: 600;
      color: var(--el-text-color-primary);
    }
  }

  .title-divider {
    margin-top: 4px;
    margin-bottom: 20px;
  }

  .dialog-content {
    text-align: left;
  }
}

.stat-card {
  text-align: left;
  padding: 5px;
  background: rgba(var(--el-color-primary-rgb), 0.02);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;

  .stat-label {
    font-size: 14px;
    color: var(--el-text-color-regular);
    margin-bottom: 8px;
  }

  .stat-value {
    font-size: 24px;
    font-weight: 600;
    color: var(--el-text-color-primary);
    margin-bottom: 4px;
  }

  .stat-detail {
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
}

.section-title {
  font-size: 16px;
  font-weight: 500;
  color: var(--el-text-color-primary);
  margin-bottom: 12px;
  text-align: left;
  padding-left: 4px;
}

.data-card {
  background: rgba(var(--el-color-info-rgb), 0.02);
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;

  :deep(.el-table) {
    background: transparent;

    .el-table__body-wrapper {
      background: transparent;
    }

    .el-table__row {
      background: transparent;

      &:hover {
        background: rgba(var(--el-color-primary-rgb), 0.05);
      }
    }
  }
}

.status-code-list {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;

  .status-tag {
    font-size: 14px;
    padding: 8px 16px;
  }
}

// Responsive design - Mobile devices (< 768px)
@media (max-width: 767px) {
  .header-section {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }

  .search-input {
    width: 100% !important;
    margin-top: 0 !important;
  }

  .table-wrapper {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  .api-details-dialog {
    :deep(.el-dialog) {
      width: 95% !important;
      margin: 3vh auto !important;
      max-height: 94vh;
      border-radius: 8px;
    }

    :deep(.el-dialog__header) {
      padding: 16px 16px 8px 16px;
    }

    :deep(.el-dialog__body) {
      padding: 0 16px 16px 16px;
      max-height: 75vh;
      overflow-y: auto;
      -webkit-overflow-scrolling: touch;
    }

    .dialog-title {
      font-size: 16px !important;
      font-weight: 600;
      line-height: 1.4;
    }

    .title-divider {
      margin: 8px 0 16px 0;
    }

    .stat-card {
      margin-bottom: 12px;
      padding: 12px !important;

      .stat-label {
        font-size: 13px !important;
        margin-bottom: 6px;
      }

      .stat-value {
        font-size: 18px !important;
        line-height: 1.2;
      }

      .stat-detail {
        font-size: 11px !important;
        margin-top: 4px;
      }
    }

    .section-title {
      font-size: 14px !important;
      margin-bottom: 8px;
      font-weight: 500;
    }

    :deep(.el-table) {
      font-size: 12px;

      .el-table__cell {
        padding: 6px 4px !important;
      }

      .el-table__header {
        th {
          font-size: 11px;
          font-weight: 600;
        }
      }
    }

    :deep(.el-tag) {
      font-size: 10px !important;
      padding: 2px 6px !important;
    }
  }
}

// Tablet devices (768px - 1023px)
@media (min-width: 768px) and (max-width: 1023px) {
  .header-section {
    align-items: center;
    flex-direction: row;
    flex-wrap: wrap;
    gap: 12px;
  }

  .search-input {
    width: 280px !important;
  }

  .api-details-dialog {
    :deep(.el-dialog) {
      width: 90% !important;
      max-width: 700px;
      margin: 5vh auto !important;
      max-height: 90vh;
    }

    :deep(.el-dialog__body) {
      padding: 20px 20px;
      max-height: 70vh;
      overflow-y: auto;
    }

    .stat-card {
      margin-bottom: 16px;

      .stat-value {
        font-size: 22px !important;
      }
    }

    .section-title {
      font-size: 15px !important;
      margin-bottom: 10px;
    }

    :deep(.el-table .el-table__cell) {
      padding: 10px 8px !important;
      font-size: 13px;
    }
  }
}

// Large tablets and small desktops (1024px - 1199px)
@media (min-width: 1024px) and (max-width: 1199px) {
  .api-details-dialog {
    :deep(.el-dialog) {
      width: 85% !important;
      max-width: 800px;
    }
  }
}

// Touch device optimizations
@media (hover: none) and (pointer: coarse) {
  .api-table {
    :deep(.el-table__row) {
      &:hover {
        background-color: transparent !important;
      }

      &:active {
        background-color: var(--el-color-primary-light-9) !important;
      }
    }
  }

  .api-details-dialog {
    :deep(.el-button) {
      min-height: 44px;
      padding: 12px 16px;
    }

    :deep(.el-dialog__close) {
      font-size: 20px;
      padding: 12px;
    }
  }
}

// High DPI displays optimization
@media (-webkit-min-device-pixel-ratio: 2), (min-resolution: 192dpi) {
  .api-details-dialog {
    .stat-card {
      border-width: 0.5px;
    }

    .data-card {
      border-width: 0.5px;
    }
  }
}
</style>
