<script setup lang="ts">
import { getConfig } from '@/api/configApi';
import type { ApiConfigs, DefaultSettings, ServerConfig } from '@/types/nekoConf';
import type { FormInstance } from 'element-plus';
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, reactive, ref } from 'vue';

import ApiSetting from './components/ApiSetting.vue';
import DefaultSetting from './components/DefaultSetting.vue';
import ServerSetting from './components/ServerSetting.vue';

const serverFormRef = ref<FormInstance>();
const defaultsFormRef = ref<FormInstance>();
const apisFormRef = ref<FormInstance>();

const serverConfig = reactive<ServerConfig>({
  host: '0.0.0.0',
  port: 8080,
  api_key: '',
  logging: {
    enabled: true,
    level: 'info',
    log_file: 'app.log'
  },
  proxy: {
    enabled: false,
    address: ''
  },
  dashboard: {
    enabled: true
  },
  queue: {
    enabled: false,
    max_size: 200,
    expiry_seconds: 300
  },
  cors: {
    allow_credentials: true,
    allow_origins: ['*'],
    allow_methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allow_headers: ['*']
  }
});

const defaultSettings = reactive<DefaultSettings>({
  key_variable: 'keys',
  load_balancing_strategy: 'round_robin',
  rate_limit: {
    endpoint_rate_limit: '10/s',
    ip_rate_limit: '10/m',
    key_rate_limit: '10/m',
    rate_limit_paths: ['*']
  },
  retry: {
    enabled: true,
    mode: 'key_rotation',
    attempts: 3,
    retry_after_seconds: 1,
    retry_request_methods: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'],
    retry_status_codes: [500, 502, 503, 504, 429]
  },
  timeouts: {
    request_timeout_seconds: 300
  },
  simulated_streaming: {
    enabled: false,
    delay_seconds: 0.2,
    init_delay_seconds: 0.5,
    chunk_size_bytes: 256,
    apply_to: ['application/xml', 'text/plain', 'image/png', 'image/jpeg']
  },
  request_body_substitution: {
    enabled: false,
    rules: [
      {
        name: 'Remove frequency_penalty',
        operation: 'remove',
        path: 'frequency_penalty',
        conditions: [
          {
            field: 'frequency_penalty',
            operator: 'exists'
          }
        ]
      },
      {
        name: 'Remove presence_penalty',
        operation: 'remove',
        path: 'presence_penalty',
        conditions: [
          {
            field: 'presence_penalty',
            operator: 'exists'
          }
        ]
      }
    ]
  }
});

const apiConfigs = reactive<ApiConfigs>({});

const fetchConfig = async () => {
  try {
    const config = await getConfig();

    // Update serverConfig properties
    if (config.server) {
      Object.assign(serverConfig, config.server);
    }

    // Update defaultSettings properties
    if (config.defaults_settings) {
      Object.assign(defaultSettings, config.defaults_settings);
    }

    // Update apiConfigs
    if (config.apis) {
      Object.assign(apiConfigs, config.apis);
    }
  } catch (error) {
    console.error('Failed to load configuration:', error);
    ElMessage.error('Failed to load configuration');
  }
};

// Active tab
const activeTab = ref('server');

const saveConfig = async () => {
  try {
    const [serverValid, defaultsValid] = await Promise.all([
      serverFormRef.value?.validate(),
      defaultsFormRef.value?.validate()
    ]);

    if (serverValid && defaultsValid) {
      // Here you would typically send the config to your API
      ElMessage.success('Configuration saved successfully!');
    }
  } catch (error) {
    console.error('Validation failed:', error);
    ElMessage.error('Please fix validation errors before saving');
  }
};

const resetConfig = () => {
  ElMessageBox.confirm('Are you sure you want to reset all configurations?', 'Warning', {
    confirmButtonText: 'Reset',
    cancelButtonText: 'Cancel',
    type: 'warning'
  }).then(() => {
    // Reset logic here
    ElMessage.success('Configuration reset successfully!');
  });
};

onMounted(() => {
  fetchConfig();
});
</script>

<template>
  <div class="config-container">
    <!-- Header -->
    <div class="config-header">
      <div class="header-content">
        <div class="title-section">
          <span class="config-title">
            <el-icon class="title-icon"><Setting /></el-icon>
            <span>NyaProxy Configuration</span>
          </span>
          <p class="config-subtitle">Manage your proxy server configuration settings</p>
        </div>
        <div class="action-buttons">
          <el-button disabled type="primary" @click="saveConfig">
            <el-icon><Check /></el-icon>
            <span>Save</span>
          </el-button>
          <el-button disabled @click="resetConfig">
            <el-icon><RefreshLeft /></el-icon>
            <span>Reset</span>
          </el-button>
        </div>
      </div>
    </div>

    <!-- Main Content -->
    <div class="config-content">
      <el-tabs v-model="activeTab" class="config-tabs">
        <!-- Server Configuration -->
        <el-tab-pane label="Server Settings" name="server">
          <ServerSetting v-model="serverConfig" ref="serverFormRef" />
        </el-tab-pane>

        <!-- Default Settings -->
        <el-tab-pane label="Default Settings" name="defaults">
          <DefaultSetting v-model="defaultSettings" ref="defaultsFormRef" />
        </el-tab-pane>

        <!-- API Configuration -->
        <el-tab-pane label="API Configuration" name="apis">
          <ApiSetting v-model="apiConfigs" ref="apisFormRef" />
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.config-container {
  padding: 20px;
  background-color: var(--el-bg-color);
  border-radius: var(--el-border-radius-base);
  box-shadow: var(--el-box-shadow-light);
  transition: all 0.3s ease;

  @media (max-width: 768px) {
    box-shadow: none;
  }

  .config-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;

    .header-content {
      width: 100%;
      display: flex;
      justify-content: space-between;

      @media (max-width: 768px) {
        flex-direction: column;
        gap: 12px;
      }

      .title-section {
        display: flex;
        flex-direction: column;
        justify-content: center;

        .config-title {
          display: flex;
          align-items: flex-start;
          justify-content: flex-start;
          font-size: 18px;
          font-weight: 600;
        }

        .title-icon {
          color: var(--el-color-primary);
          font-size: 24px;
          margin-right: 5px;
        }
      }

      .config-subtitle {
        color: var(--el-text-color-secondary);
        font-size: var(--el-font-size-small);
      }
    }

    .action-buttons {
      gap: 12px;

      .el-button {
        min-width: 120px;
      }

      @media (max-width: 768px) {
        flex-direction: column;

        .el-button {
          width: 100%;
          margin-left: 0;
          margin-top: 8px;
        }
      }
    }
  }
}
</style>
