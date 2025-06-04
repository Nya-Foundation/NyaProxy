<script setup lang="ts">
import { useAppSettings } from '@/hooks/useAppSetting';
import { routes } from '@/router';
import type { AppRouteRecordRaw } from '@/types/router';
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import SidebarItem from './SidebarItem.vue';

const route = useRoute();
const router = useRouter();
const subMenuData = ref<AppRouteRecordRaw[]>([]);
const { appConfig } = useAppSettings();

const menuData = computed<AppRouteRecordRaw[]>(() => {
  return subMenuData.value;
});

function getSubMenuData(currentPath: string) {
  let newSubMenu: AppRouteRecordRaw[] = [];

  let relevantParentRecord: AppRouteRecordRaw | undefined = undefined;

  if (route.matched.length > 0) {
    relevantParentRecord = route.matched[0] as AppRouteRecordRaw;
  }
  if (
    relevantParentRecord &&
    relevantParentRecord.children &&
    relevantParentRecord.children.length > 0
  ) {
    newSubMenu = relevantParentRecord.children as AppRouteRecordRaw[];
  } else {
    const homeRoute = routes.find(r => r.path === '/');
    newSubMenu = homeRoute?.children || [];
  }

  subMenuData.value = newSubMenu;
}

watch(
  () => route.path,
  newPath => {
    getSubMenuData(newPath);
  },
  { immediate: true }
);

const activeMenu = computed<string>(() => {
  const { meta, path } = route;
  return (meta?.activeMenu || path) as string;
});

// Collapse state
const collapse = computed(() => appConfig.value.collapseMenu);
</script>

<template>
  <el-scrollbar wrap-class="scrollbar-wrapper">
    <el-menu
      :default-active="activeMenu"
      :unique-opened="true"
      :collapse="collapse"
      mode="vertical"
      :collapse-transition="true"
      router
    >
      <SidebarItem
        v-for="menuRoute in menuData"
        :key="menuRoute.path"
        :item="menuRoute"
        :is-nest="false"
        :base-path="menuRoute.path"
        :collapse="collapse"
      />
    </el-menu>
  </el-scrollbar>
</template>
