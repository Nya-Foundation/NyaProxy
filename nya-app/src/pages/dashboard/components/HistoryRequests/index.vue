<script lang="ts" setup>
import { useHistoryStore } from '@/stores/modules/history';
import { storeToRefs } from 'pinia';
import { computed } from 'vue';

const historyStore = useHistoryStore();
const { dataHistory } = storeToRefs(historyStore);

const dateFilters = computed(() => {
  const dates = new Set<string>();
  dataHistory.value.forEach((item: any) => {
    const date = item.time.split(' ')[0];
    dates.add(date);
  });
  return Array.from(dates)
    .sort()
    .reverse()
    .slice(0, 10) // Limit to recent 10 dates
    .map(date => ({ text: date, value: date }));
});

const apiNameFilters = computed(() => {
  const apiNames = new Set<string>();
  dataHistory.value.forEach((item: any) => {
    apiNames.add(item.apiName);
  });
  return Array.from(apiNames)
    .sort()
    .map(name => ({ text: name, value: name }));
});

const filterByDate = (value: string, row: any) => {
  const rowDate = row.time.split(' ')[0];
  return rowDate === value;
};

const filterByApiName = (value: string, row: any) => {
  return row.apiName === value;
};
</script>

<template>
  <div class="mt-5">
    <!-- Header Section -->
    <div class="header-section mb-2 px-2 py-1">
      <div class="flex items-center text-lg md:text-xl">
        <el-icon color="var(--el-color-primary)">
          <Histogram />
        </el-icon>
        <span class="ml-1">History Requests</span>
      </div>
    </div>

    <!-- Content Container -->
    <el-card shadow="hover">
      <div class="table-wrapper">
        <el-table :data="dataHistory" table-layout="auto" class="api-table">
          <el-table-column
            prop="time"
            label="TIME"
            min-width="120"
            :filters="dateFilters"
            :filter-method="filterByDate"
            filter-placement="bottom-end"
          />

          <el-table-column
            prop="apiName"
            label="API NAME"
            min-width="120"
            :filters="apiNameFilters"
            :filter-method="filterByApiName"
            filter-placement="bottom-end"
          />

          <el-table-column prop="status" label="STATUS" min-width="120">
            <template #default="{ row }">
              <span
                class="status-badge"
                :style="{
                  backgroundColor:
                    row.status === 200
                      ? 'var(--el-color-success-light-8)'
                      : 'var(--el-color-warning-light-8)',
                  color: row.status === 200 ? 'var(--el-color-success)' : 'var(--el-color-warning)'
                }"
              >
                {{ row.status }}
              </span>
            </template>
          </el-table-column>

          <el-table-column prop="ResponseTime" label="RESPONSE TIME" min-width="120" />

          <el-table-column prop="apiKey" label="API KEY" min-width="120" />
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<style lang="scss" scoped>
.status-badge {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
  line-height: 1;
  user-select: none;
}
</style>
