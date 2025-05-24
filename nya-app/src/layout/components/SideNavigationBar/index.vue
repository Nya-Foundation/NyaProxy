<script setup lang="ts">
import SideBarDisplay from './SideBarDisplay.vue';
import { useAppSettings } from '@/hooks/useAppSetting';
import { useDebounceFn, useEventListener, useMediaQuery } from '@vueuse/core';
import { ref, watch } from 'vue';

const { appConfig, setAppConfigMode } = useAppSettings();

const drawer = ref<boolean>(!appConfig.value.collapseMenu);

const setAppStore = (appData: Partial<AppConfig>) => {
  setAppConfigMode(appData);
};

const handleClose = () => {
  setAppStore({
    collapseMenu: drawer.value
  });
};

const isPhoneScreen = ref<boolean>(false);
const isSmallScreen = ref<boolean>(false);

const mediaQuery = useDebounceFn(() => {
  isSmallScreen.value = useMediaQuery('(max-width: 1024px)').value;

  isPhoneScreen.value = useMediaQuery('(max-width: 750px)').value;
  if (isPhoneScreen.value) {
    setAppStore({ drawerSidebar: true });
  } else {
    setAppStore({ drawerSidebar: false });
  }
}, 100);

watch(isSmallScreen, () => {
  setAppStore({
    collapseMenu: isSmallScreen.value
  });
});

watch(
  () => appConfig.value.collapseMenu,
  () => {
    drawer.value = !appConfig.value.collapseMenu;
  }
);

useEventListener(window, 'resize', () => mediaQuery());

mediaQuery();
</script>

<template>
  <el-drawer
    v-if="isPhoneScreen"
    v-model="drawer"
    :with-header="false"
    direction="ltr"
    :before-close="handleClose"
    class="drawer-sidebar"
  >
    <SideBarDisplay />
  </el-drawer>
  <template v-else>
    <SideBarDisplay />
  </template>
</template>

<style lang="scss">
.drawer-sidebar {
  width: $side-bar-width !important;
  background-color: var(--main-bg-color);

  .el-drawer__body {
    height: 100vh;
    padding: 0 !important;
    overflow: hidden;

    .sidebar-container {
      height: 100%;
    }
  }
}
</style>
