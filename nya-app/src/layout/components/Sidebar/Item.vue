<script setup lang="ts">
import { useTemplateRef, ref } from 'vue';

type Props = {
  icon?: string;
  title?: string;
  className?: string;
  collapse?: boolean;
};

const props = withDefaults(defineProps<Props>(), {
  icon: '',
  title: '',
  className: '',
  collapse: false
});

const showTextTooltip = ref<boolean | null>(null);
const sidebarItemTextRef = useTemplateRef<HTMLDivElement>('sidebar-item-text-ref');

const onTextMove = () => {
  if (showTextTooltip.value !== null) return;
  const sidebarItemTextDom = sidebarItemTextRef.value?.children?.[0];
  showTextTooltip.value = sidebarItemTextDom
    ? sidebarItemTextDom.scrollWidth > sidebarItemTextDom.clientWidth
    : false;
};
</script>

<template>
  <el-icon v-if="props.icon" :class="props.className">
    <component :is="props.icon" />
  </el-icon>
  <div
    ref="sidebar-item-text-ref"
    class="menu-item-text sidebar-menu-item-text"
    :class="[!props.icon && 'menu-item-text-only']"
    @mouseover="onTextMove"
  >
    <el-tooltip
      :content="props.title"
      :disabled="!showTextTooltip || props.collapse"
      placement="top"
    >
      <el-text truncated>
        {{ props.title }}
      </el-text>
    </el-tooltip>
  </div>
</template>

<style lang="scss" scoped>
.sidebar-menu-item-text {
  flex: 1;
  width: 0;
}

.menu-item-text {
  color: currentcolor;

  .el-text {
    color: currentcolor;
  }
}

.menu-item-text-only {
  padding-left: 20px;
}
</style>
