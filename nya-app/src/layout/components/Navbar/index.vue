<script setup lang="ts">
import { AppTheme } from '@/components/Application';
import { useAppSettings } from '@/hooks/useAppSetting';

const { appConfig, setAppConfigMode } = useAppSettings();

const handerShowElmenu = () => {
  setAppConfigMode({
    collapseMenu: !appConfig.value.collapseMenu
  });
};
</script>

<template>
  <div class="navbar">
    <div class="navbar-content">
      <div class="navbar-left">
        <el-icon
          class="sidebar-fold cursor"
          :class="{ 'sidebar-unfold': appConfig.collapseMenu }"
          @click="handerShowElmenu"
        >
          <Fold />
        </el-icon>
      </div>
      <div class="navbar-right">
        <div class="setting"><AppTheme /></div>
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.sidebar-fold {
  margin-left: 10px;
}

.sidebar-unfold {
  transform: rotate(180deg);
}

.navbar {
  width: 100%;
  border-bottom: 1px solid var(--border-color-light);
  // margin-left: #{$side-bar-width};
  background-color: $nav-bar-color;
  box-shadow: 1px 0 20px rgb(0 0 0 / 8%);

  .navbar-content {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    height: #{$nav-bar-height};
    font-size: var(--font-size-extra-large);

    .navbar-left {
      display: flex;
      align-items: center;
    }

    .navbar-right {
      display: grid;
      grid-auto-flow: column;
      grid-gap: 10px;
      align-items: center;
      margin-right: 10px;

      .setting {
        padding-right: 5px;
      }
    }
  }
}
</style>
