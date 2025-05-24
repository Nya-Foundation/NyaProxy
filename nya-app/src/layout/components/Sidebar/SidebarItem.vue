<script setup lang="ts">
import { isUrl } from '@jsxiaosi/utils';
import { ref } from 'vue';
import type { AppRouteRecordRaw } from '@/types/router';
import Item from './Item.vue';

type Props = {
  item: AppRouteRecordRaw;
  isNest: boolean;
  basePath: string;
  level?: number;
  collapse: boolean;
};

const props = withDefaults(defineProps<Props>(), {
  isNest: false,
  basePath: '',
  level: 0,
  collapse: false
});

const onlyOneChild = ref<Partial<AppRouteRecordRaw & { noShowingChildren: boolean }>>({});

const hasOneShowingChild = (parent: AppRouteRecordRaw) => {
  const showingChildren =
    parent.children?.filter((item: AppRouteRecordRaw) => {
      // Filter out hidden routes or routes without title
      if (item.meta?.hidden) return false;
      if (!item.meta?.title) return false;

      // Temp set(will be used if only has one showing child)
      onlyOneChild.value = item;
      return true;
    }) ?? [];

  // When there is only one child router, the child router is displayed by default
  if (showingChildren.length === 1) {
    return true;
  }

  // Show parent if there are no child router to display
  if (showingChildren.length === 0) {
    onlyOneChild.value = { ...parent, path: '', noShowingChildren: true };
    return true;
  }

  return false;
};

const resolvePath = (routePath: string) => {
  if (isUrl(routePath)) {
    return routePath;
  }
  if (isUrl(props.basePath)) {
    return props.basePath;
  }
  return `${props.basePath.replace(/\/$/, '')}/${routePath.replace(/^\//, '')}`;
};

// Helper function to translate i18n (placeholder implementation)
const translateI18n = (key?: string) => {
  return key || '';
};
</script>

<template>
  <div class="sidebar-item">
    <template
      v-if="
        hasOneShowingChild(props.item) &&
        (!onlyOneChild.children || onlyOneChild.noShowingChildren) &&
        !props.item.meta?.alwaysShow
      "
    >
      <el-tooltip
        class="box-item"
        :disabled="props.level > 0 || !props.collapse"
        :content="translateI18n(onlyOneChild.meta?.title)"
        placement="right"
      >
        <el-menu-item
          v-if="onlyOneChild.meta"
          :index="resolvePath(onlyOneChild?.path ?? '')"
          :class="{
            'submenu-title-no-dropdown': !props.isNest,
            'one-level-menu-item': props.level === 0
          }"
        >
          <Item
            class-name="menu-item-svg"
            :icon="onlyOneChild.meta.icon || (props.item.meta && props.item.meta.icon)"
            :title="onlyOneChild.meta.title || (props.item.meta && props.item.meta.title)"
            :collapse="props.level === 0 && props.collapse"
          />
        </el-menu-item>
      </el-tooltip>
    </template>

    <el-sub-menu
      v-else
      :index="resolvePath(props.item.path)"
      :class="{ 'one-level-sub-menu': props.level === 0 }"
      teleported
    >
      <template #title>
        <Item
          v-if="props.item.meta"
          class-name="sub-menu-svg"
          :icon="props.item.meta && props.item.meta.icon"
          :title="props.item.meta.title"
          :collapse="props.level === 0 && props.collapse"
        />
      </template>

      <sidebar-item
        v-for="(child, index) in props.item.children"
        :key="child.path + index"
        :is-nest="true"
        :item="child"
        :base-path="resolvePath(child.path)"
        class="nest-menu"
        :level="props.level + 1"
        :collapse="props.collapse"
      />
    </el-sub-menu>
  </div>
</template>
