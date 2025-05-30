<script setup lang="ts">
import type { FormInstance } from 'element-plus';
import { ref } from 'vue';

import type { DefaultSettings } from '@/types/nekoConf';

defineProps({
  modelValue: {
    type: Object as () => DefaultSettings,
    required: true
  }
});

const defaultsFormRef = ref<FormInstance>();

const loadBalancingStrategies = ['round_robin', 'least_requests'];

const contentTypes = [
  'application/json',
  'application/xml',
  'text/plain',
  'text/html',
  'image/png',
  'image/jpeg',
  'image/gif'
];

const emit = defineEmits(['update:modelValue']);

defineExpose({
  validate: () => {
    return defaultsFormRef.value?.validate();
  }
});
</script>

<template>
  <div class="tab-content">
    <el-form ref="defaultsFormRef" :model="modelValue" label-width="180px" class="config-form">
      <!-- Load Balancing -->
      <div class="form-section">
        <div class="section-header">
          <h3>
            <el-icon><Grid /></el-icon> Load Balancing
          </h3>
        </div>
        <div class="form-grid">
          <el-form-item label="Key Variable" class="half-width">
            <el-input v-model="modelValue.key_variable" />
          </el-form-item>
          <el-form-item label="Strategy" class="half-width">
            <el-select v-model="modelValue.load_balancing_strategy">
              <el-option
                v-for="strategy in loadBalancingStrategies"
                :key="strategy"
                :label="strategy.replace('_', ' ').toUpperCase()"
                :value="strategy"
              />
            </el-select>
          </el-form-item>
        </div>
      </div>

      <!-- Rate Limiting -->
      <div class="form-section">
        <div class="section-header">
          <h3>
            <el-icon><Timer /></el-icon> Rate Limiting
          </h3>
        </div>
        <div class="form-grid">
          <el-form-item label="Endpoint Rate Limit">
            <el-input v-model="modelValue.rate_limit.endpoint_rate_limit" placeholder="10/s" />
          </el-form-item>
          <el-form-item label="IP Rate Limit">
            <el-input v-model="modelValue.rate_limit.ip_rate_limit" placeholder="10/m" />
          </el-form-item>
          <el-form-item label="Key Rate Limit">
            <el-input v-model="modelValue.rate_limit.key_rate_limit" placeholder="10/m" />
          </el-form-item>
          <el-form-item label="Rate Limit Paths" class="full-width">
            <el-select
              v-model="modelValue.rate_limit.rate_limit_paths"
              multiple
              filterable
              allow-create
              default-first-option
              :reserve-keyword="false"
              placeholder="Enter paths to rate limit"
            >
              <el-option label="All paths (*)" value="*" />
            </el-select>
          </el-form-item>
        </div>
      </div>

      <!-- Retry Configuration -->
      <div class="form-section">
        <div class="section-header">
          <h3>
            <el-icon><Refresh /></el-icon> Retry Settings
          </h3>
        </div>
        <div class="form-grid">
          <el-form-item label="Enable Retry">
            <el-switch v-model="modelValue.retry.enabled" />
          </el-form-item>
          <el-form-item label="Retry Mode" class="half-width">
            <el-select
              v-model="modelValue.retry.mode"
              :disabled="!modelValue.retry.enabled"
              filterable
              allow-create
              default-first-option
              :reserve-keyword="false"
            >
              <el-option label="Key Rotation" value="key_rotation" />
            </el-select>
          </el-form-item>
          <el-form-item label="Max Attempts" class="half-width">
            <el-input-number
              v-model="modelValue.retry.attempts"
              :disabled="!modelValue.retry.enabled"
              :min="1"
              :controls="false"
            />
          </el-form-item>
          <el-form-item label="Retry After (seconds)" class="half-width">
            <el-input-number
              v-model="modelValue.retry.retry_after_seconds"
              :disabled="!modelValue.retry.enabled"
              :min="0.1"
              :step="0.1"
              :controls="false"
            />
          </el-form-item>
        </div>
      </div>

      <!-- Simulated Streaming -->
      <div class="form-section">
        <div class="section-header">
          <h3>
            <el-icon><VideoPlay /></el-icon> Simulated Streaming
          </h3>
        </div>
        <div class="form-grid">
          <el-form-item label="Enable Streaming">
            <el-switch v-model="modelValue.simulated_streaming.enabled" />
          </el-form-item>
          <el-form-item label="Delay (seconds)">
            <el-input-number
              v-model="modelValue.simulated_streaming.delay_seconds"
              :disabled="!modelValue.simulated_streaming.enabled"
              :min="0.01"
              :step="0.01"
              :controls="false"
            />
          </el-form-item>
          <el-form-item label="Chunk Size (bytes)">
            <el-input-number
              v-model="modelValue.simulated_streaming.chunk_size_bytes"
              :disabled="!modelValue.simulated_streaming.enabled"
              :min="1"
              :controls="false"
            />
          </el-form-item>
          <el-form-item label="Apply to Content Types" class="full-width">
            <el-select
              v-model="modelValue.simulated_streaming.apply_to"
              :disabled="!modelValue.simulated_streaming.enabled"
              multiple
              filterable
              allow-create
              default-first-option
              :reserve-keyword="false"
            >
              <el-option v-for="type in contentTypes" :key="type" :label="type" :value="type" />
            </el-select>
          </el-form-item>
        </div>
      </div>
    </el-form>
  </div>
</template>

<style scoped lang="scss">
.tab-content {
  .config-form {
    .form-section {
      margin-bottom: 1rem;
      padding: 1rem;

      .section-header {
        display: flex;
        align-items: center;
        margin-bottom: 16px;

        .el-icon {
          margin-right: 8px;
          color: var(--el-color-primary);
        }

        span {
          font-weight: bold;
        }
      }

      .form-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 16px;

        .el-input-number {
          width: 50%;
        }

        @media (max-width: 768px) {
          grid-template-columns: 1fr;
        }

        .el-form-item {
          .el-input,
          .el-select {
            width: 100%;
          }

          &.full-width {
            grid-column: 1 / -1;
          }

          &.half-width {
            grid-column: span 1;
          }
        }
      }
    }
  }
}
</style>
