<script setup lang="ts">
import { useTheme } from '@/hooks/useTheme';

const { color } = useTheme();
</script>

<template>
  <div
    class="theme cursor"
    :class="{ 'theme-dark': color === 'dark' }"
    @click="
      () => {
        color = color === 'dark' ? 'light' : 'dark';
      }
    "
  >
    <el-icon v-show="color === 'light'">
      <Sunny />
    </el-icon>
    <el-icon v-show="color === 'dark'">
      <Moon />
    </el-icon>
  </div>
</template>

<style lang="scss" scoped>
.theme {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  transition: background-color 0.3s, border-color 0.3s;

  &:hover {
    cursor: pointer;
  }
}

.el-icon {
  font-size: 1em;
}
</style>
