<script lang="ts" setup>
import type { ApiConfigs } from '@/types/nekoConf';

const props = defineProps({
  modelValue: {
    type: Object as () => ApiConfigs,
    required: true
  }
});

const emit = defineEmits(['update:modelValue']);

const newConfigs = { ...props.modelValue };

const addApiConfig = () => {
  const name = `api_${Date.now()}`;
  newConfigs[name] = {
    name: 'New API',
    endpoint: 'https://api.example.com/v1',
    aliases: ['/api'],
    key_variable: 'keys',
    headers: {
      Authorization: 'Bearer ${{keys}}'
    },
    variables: {
      keys: ['your_api_key']
    },
    load_balancing_strategy: 'least_requests',
    rate_limit: {
      endpoint_rate_limit: '300/d',
      key_rate_limit: '5/m',
      rate_limit_paths: ['*']
    }
  };
  emit('update:modelValue', newConfigs);
};

const removeApiConfig = (key: string) => {
  delete newConfigs[key];
  emit('update:modelValue', newConfigs);
};

const addVariable = (apiKey: string, varName: string) => {
  const targetApi = newConfigs[apiKey]
  if (!targetApi) return // 防止空指针

  // 初始化 variables 对象
  if (!targetApi.variables) {
    targetApi.variables = {}
  }

  // 初始化具体变量数组
  if (!targetApi.variables[varName]) {
    targetApi.variables[varName] = []
  }

  targetApi.variables[varName].push('');
  emit('update:modelValue', newConfigs);
};

const removeVariable = (apiKey: string, varName: string, index: number) => {
  newConfigs[apiKey].variables[varName].splice(index, 1);
  emit('update:modelValue', newConfigs);
};

const loadBalancingStrategies = ['round_robin', 'least_requests'];
</script>

<template>
  <div class="tab-content">
    <div class="api-header">
      <h3>API Endpoints</h3>
      <!-- 未实现，不使用 -->
      <!-- <el-button type="primary" @click="addApiConfig">
        <el-icon><Plus /></el-icon>
        <span>Add API</span>
      </el-button> -->
    </div>

    <div class="api-list">
      <el-card v-for="(config, key) in modelValue" :key="key" class="api-card" shadow="hover">
        <template #header>
          <div class="api-card-header">
            <div class="api-info">
              <h4>{{ config.name }}</h4>
              <el-tag size="small" type="info">{{ key }}</el-tag>
            </div>
            <!-- 未实现，不使用  -->
            <!-- <el-button type="danger" size="small" @click="removeApiConfig(key)">
              <el-icon><Delete /></el-icon>
            </el-button> -->
          </div>
        </template>

        <el-form :model="config" label-width="120px" class="api-form">
          <el-row :gutter="20">
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item label="API Name">
                <el-input v-model="config.name" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="24" :md="24">
              <el-form-item label="Endpoint URL">
                <el-input v-model="config.endpoint" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item label="Load Balancing">
                <el-select
                  v-model="config.load_balancing_strategy"
                  filterable
                  allow-create
                  default-first-option
                  :reserve-keyword="false"
                >
                  <el-option
                    v-for="strategy in loadBalancingStrategies"
                    :key="strategy"
                    :label="strategy.replace('_', ' ').toUpperCase()"
                    :value="strategy"
                  />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>

          <!-- Aliases -->
          <div class="aliases-section" v-if="(config.aliases?.length ?? 0) > 0">
            <h5>
              <el-icon><Link /></el-icon>
              Aliases
            </h5>
            <el-select
              v-model="config.aliases"
              multiple
              filterable
              allow-create
              default-first-option
              :reserve-keyword="false"
              class="aliases-select"
            >
            </el-select>
          </div>

          <!-- Headers -->
          <div class="headers-section">
            <h5>
              <el-icon><Document /></el-icon> Headers
            </h5>
            <div
              v-for="(value, headerName) in config.headers"
              :key="headerName"
              class="header-group"
            >
              <el-row :gutter="20">
                <el-col :xs="24" :sm="12">
                  <el-form-item :label="headerName">
                    <el-input v-model="config.headers[headerName]" />
                  </el-form-item>
                </el-col>
              </el-row>
            </div>
          </div>

          <!-- API Variables -->
          <div class="variables-section">
            <h5>
              <el-icon><Key /></el-icon> Variables
            </h5>
            <div
              v-for="(values, varName) in config.variables"
              :key="varName"
              class="variable-group"
            >
              <div class="variable-header">
                <span class="variable-name">{{ varName }}</span>
                <el-button disabled size="small" type="primary" @click="addVariable(key, varName)">
                  <el-icon><Plus /></el-icon>
                  <span>Add</span>
                </el-button>
              </div>
              <div class="variable-values">
                <div v-for="(value, index) in values" :key="index" class="variable-value">
                  <el-row :gutter="20">
                    <el-col :xs="20" :sm="20">
                      <el-input v-model="config.variables[varName][index]" />
                    </el-col>
                    <el-col :xs="4" :sm="4">
                      <el-button
                        disabled
                        type="danger"
                        size="small"
                        @click="removeVariable(key, varName, index)"
                      >
                        <el-icon><Delete /></el-icon>
                      </el-button>
                    </el-col>
                  </el-row>
                </div>
              </div>
            </div>
          </div>

          <!-- Rate Limiting -->
          <div class="rate-limit-section">
            <h5>
              <el-icon><Timer /></el-icon> Rate Limits
            </h5>
            <el-row :gutter="20">
              <el-col :xs="24" :sm="12" :md="8">
                <el-form-item label="Endpoint Limit">
                  <el-input v-model="config.rate_limit.endpoint_rate_limit" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12" :md="8">
                <el-form-item label="Key Limit">
                  <el-input v-model="config.rate_limit.key_rate_limit" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="24" :md="24">
                <el-form-item label="Rate Limit Paths">
                  <el-select
                    v-model="config.rate_limit.rate_limit_paths"
                    multiple
                    filterable
                    allow-create
                    default-first-option
                    :reserve-keyword="false"
                  >
                    <el-option label="*" value="*" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
          </div>
        </el-form>
      </el-card>
    </div>
  </div>
</template>

<style scoped lang="scss">
.api-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding: 0 10px;
}

.api-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

:deep(.el-card__header) {
  padding: 0 1rem;
}

.api-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.api-info {
  display: flex;
  align-items: center;

  .el-tag {
    margin-left: 10px;
  }
}

.api-form {
  padding: 20px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 20px;
}

.aliases-section,
.headers-section,
.variables-section,
.rate-limit-section {
  margin-top: 1rem;
  padding: 10px;

  h5 {
    margin-bottom: 2rem;
  }
}

h5 {
  margin: 0 0 10px;
  font-size: 16px;
}

.variable-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  padding: 0 5px;
  color: var(--el-text-color-secondary);
  margin-top: 10px;
}

.variable-name {
  font-weight: bold;
}

.variable-values {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 1rem 1rem 0.5rem 1rem;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  box-shadow: var(--el-box-shadow-light);
}

.el-input,
.el-select {
  width: 100%;
}

.variable-value .el-input {
  margin-bottom: 10px;
}

.el-button + .el-button {
  margin-left: 10px;
}

@media (max-width: 768px) {
  .el-form-item {
    margin-bottom: 15px;
  }

  .el-col {
    margin-bottom: 10px;
  }
}
</style>
