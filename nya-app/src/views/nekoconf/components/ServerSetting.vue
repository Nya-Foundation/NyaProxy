<script setup lang="ts">
import { ref } from 'vue';

import type { FormInstance, FormRules } from 'element-plus';

import type { ServerConfig } from '@/types/nekoConf';

defineProps({
  modelValue: {
    type: Object as () => ServerConfig,
    required: true
  }
});

const serverFormRef = ref<FormInstance>();

const serverRules: FormRules = {
  host: [{ required: true, message: 'Please enter host address', trigger: 'blur' }],
  port: [
    { required: true, message: 'Please enter port number', trigger: 'blur' },
    { type: 'number', min: 1, max: 65535, message: 'Port must be between 1-65535', trigger: 'blur' }
  ],
  api_key: [{ required: true, message: 'Please enter API key', trigger: 'blur' }]
};

const httpMethods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'];
const logLevels = ['debug', 'info', 'warn', 'error'];

const emit = defineEmits(['update:modelValue']);

defineExpose({
  validate: () => {
    return serverFormRef.value?.validate();
  }
});
</script>

<template>
  <div class="tab-content">
    <el-form
      ref="serverFormRef"
      :model="modelValue"
      :rules="serverRules"
      label-width="150px"
      class="config-form"
    >
      <!-- Basic Settings -->
      <div class="form-section">
        <div class="section-header">
          <span>
            <el-icon><Connection /></el-icon> <span>Basic Settings</span>
          </span>
        </div>
        <div class="form-grid">
          <el-form-item label="Host Address" prop="host" class="full-width">
            <el-input v-model="modelValue.host" placeholder="0.0.0.0" />
          </el-form-item>
          <el-form-item label="Port" prop="port" class="half-width">
            <el-input-number v-model="modelValue.port" :min="1" :max="65535" :controls="false" />
          </el-form-item>
          <el-form-item label="API Key" prop="api_key" class="full-width">
            <el-input v-model="modelValue.api_key" type="password" show-password />
          </el-form-item>
        </div>
      </div>

      <!-- Logging Configuration -->
      <div class="form-section">
        <div class="section-header">
          <span>
            <el-icon><Document /></el-icon> <span>Logging</span>
          </span>
        </div>
        <div class="form-grid">
          <el-form-item label="Enable Logging" class="half-width">
            <el-switch v-model="modelValue.logging.enabled" />
          </el-form-item>
          <el-form-item
            label="Log Level"
            class="half-width"
            :class="{ 'is-disabled': !modelValue.logging.enabled }"
          >
            <el-select v-model="modelValue.logging.level" :disabled="!modelValue.logging.enabled">
              <el-option
                v-for="level in logLevels"
                :key="level"
                :label="level.toUpperCase()"
                :value="level"
              />
            </el-select>
          </el-form-item>
          <el-form-item
            label="Log File"
            class="full-width"
            :class="{ 'is-disabled': !modelValue.logging.enabled }"
          >
            <el-input
              v-model="modelValue.logging.log_file"
              :disabled="!modelValue.logging.enabled"
            />
          </el-form-item>
        </div>
      </div>

      <!-- Proxy Configuration -->
      <div class="form-section">
        <div class="section-header">
          <span>
            <el-icon><Link /></el-icon><span>Proxy</span>
          </span>
        </div>
        <div class="form-grid">
          <el-form-item label="Enable Proxy" class="half-width">
            <el-switch v-model="modelValue.proxy.enabled" />
          </el-form-item>
          <el-form-item
            label="Proxy Address"
            class="full-width"
            :class="{ 'is-disabled': !modelValue.proxy.enabled }"
          >
            <el-input
              v-model="modelValue.proxy.address"
              :disabled="!modelValue.proxy.enabled"
              placeholder="socks5://username:password@proxy.example.com:1080"
            />
          </el-form-item>
        </div>
      </div>

      <!-- Queue Configuration -->
      <div class="form-section">
        <div class="section-header">
          <span>
            <el-icon><List /></el-icon> Request <span>Queue</span>
          </span>
        </div>
        <div class="form-grid">
          <el-form-item label="Enable Queue" class="half-width">
            <el-switch v-model="modelValue.queue.enabled" />
          </el-form-item>
          <el-form-item
            label="Max Size"
            class="half-width"
            :class="{ 'is-disabled': !modelValue.queue.enabled }"
          >
            <el-input-number
              v-model="modelValue.queue.max_size"
              :disabled="!modelValue.queue.enabled"
              :min="1"
              :max="10000"
              :controls="false"
            />
          </el-form-item>
          <el-form-item
            label="Expiry (seconds)"
            class="half-width"
            :class="{ 'is-disabled': !modelValue.queue.enabled }"
          >
            <el-input-number
              v-model="modelValue.queue.expiry_seconds"
              :disabled="!modelValue.queue.enabled"
              :min="1"
              :controls="false"
            />
          </el-form-item>
        </div>
      </div>

      <!-- CORS Configuration -->
      <div class="form-section">
        <div class="section-header">
          <span>
            <el-icon><Guide /></el-icon> CORS <span>Settings</span>
          </span>
        </div>
        <div class="form-grid">
          <el-form-item label="Allow Credentials" class="half-width">
            <el-switch v-model="modelValue.cors.allow_credentials" />
          </el-form-item>
          <el-form-item label="Allowed Origins" class="full-width">
            <el-select
              v-model="modelValue.cors.allow_origins"
              multiple
              filterable
              allow-create
              default-first-option
              :reserve-keyword="false"
              placeholder="Enter allowed origins"
            >
              <el-option label="All Origins (*)" value="*" />
            </el-select>
          </el-form-item>
          <el-form-item label="Allowed Methods" class="full-width">
            <el-select v-model="modelValue.cors.allow_methods" multiple>
              <el-option
                v-for="method in httpMethods"
                :key="method"
                :label="method"
                :value="method"
              />
            </el-select>
          </el-form-item>
        </div>
      </div>
    </el-form>
  </div>
</template>

<style lang="scss" scoped>
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
