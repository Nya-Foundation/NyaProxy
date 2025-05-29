<script setup lang="ts">
import { useTheme } from '@/hooks/useTheme';

const { color } = useTheme();
</script>

<template>
  <el-button
    class="theme-button"
    :class="{ 'theme-dark': color === 'dark' }"
    @click="
      () => {
        color = color === 'dark' ? 'light' : 'dark';
      }
    "
    circle
  >
    <el-icon v-show="color === 'light'">
      <Sunny />
    </el-icon>
    <el-icon v-show="color === 'dark'">
      <Moon />
    </el-icon>
  </el-button>
</template>

<style lang="scss" scoped>
.theme-button {
  width: 32px;
  height: 32px;
  border: none;
  padding: 4px;

  &:hover {
    background-color: var(--el-fill-color-light);
  }
}

.el-icon {
  font-size: 1em;
}
</style>
