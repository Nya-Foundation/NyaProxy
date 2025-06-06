<script setup lang="ts">
import SideBar from '../Sidebar/index.vue';
import { useAppSettings } from '@/hooks/useAppSetting';
import logo from '@/assets/images/logo.svg';
import { useRouter } from 'vue-router';

const { appConfig } = useAppSettings();
const router = useRouter();

const goHome = () => {
  router.push({ path: '/dashboard' });
};
</script>

<template>
  <div class="sidebar-container" :class="{ 'hide-sidebar': appConfig.collapseMenu }">
    <div class="app-logo" :class="{ 'app-logo-hide': appConfig.collapseMenu }" @click="goHome">
      <div class="logo">
        <img class="logo-img" :src="logo" mode="scaleToFill" alt="logo" />
      </div>

      <span class="name">NyaProxy</span>
    </div>
    <SideBar />
  </div>
</template>

<style lang="scss" scoped>
.app-logo {
  display: flex;
  align-items: center;
  width: $side-bar-width;
  height: #{$nav-bar-height};
  font-size: 38px;
  justify-content: center;

  &:hover {
    cursor: pointer;
  }

  .logo {
    display: flex;
    align-items: center;
    justify-content: center;
    width: $side-hide-bar-width;

    .logo-img {
      width: 42px;
      height: 42px;
    }
  }

  .name {
    flex: 1;
    width: 100%;
    overflow: hidden;
    transition: all 0.5s;
    font-size: 22px;
    font-weight: 500;
    line-height: calc($nav-bar-height + 2px);
  }
}

.app-logo-hide {
  .name {
    transform: translateX(-20px);
    opacity: 0;
  }
}
</style>
