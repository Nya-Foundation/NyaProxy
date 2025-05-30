<script setup lang="ts">
import { useQueueStore } from '@/stores/modules/queue';
import { computed } from 'vue';

const queueStore = useQueueStore();

const tableData = computed(() => {
  const queueSizes = queueStore.dataQueue.queue_sizes || {};
  return Object.entries(queueSizes).map(([name, size]) => {
  const queueSize = size as number;
    let statusClass = 'text-green-500';
    let statusText = 'Normal';

    if (queueSize > 50) {
      statusClass = 'text-red-500';
      statusText = 'Heavy Load';
    } else if (queueSize > 10) {
      statusClass = 'text-yellow-500';
      statusText = 'Moderate Load';
    }

    return { name, size: queueSize, statusClass, statusText };
  });
});
</script>

<template>
  <div class="mt-5">
    <!-- Header Section -->
    <div class="header-section mb-2 px-2 py-1 flex justify-between items-center">
      <div class="flex items-center text-lg md:text-xl">
        <el-icon color="var(--el-color-primary)">
          <CollectionTag />
        </el-icon>
        <span class="ml-1">Queue Status</span>
      </div>
    </div>
    <!-- Queue Status Section -->
    <el-card shadow="hover">
      <el-table :data="tableData" table-layout="auto" style="width: 100%">
        <el-table-column prop="name" label="Queue Name" />
        <el-table-column prop="size" label="Size" />
        <el-table-column label="Status">
          <template #default="{ row }">
            <span :class="row.statusClass">{{ row.statusText }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
