<script setup lang="ts"></script>

<template>
  <section class="app-main">
    <router-view>
      <template #default="{ Component, route }">
        <transition name="fade-transform" mode="out-in">
          <keep-alive>
            <component :is="Component" :key="route.fullPath" />
          </keep-alive>
        </transition>
      </template>
    </router-view>
  </section>
</template>

<style lang="scss">
.app-main {
  position: relative;
  // height: calc(100vh - #{$nav-bar-height+$tabs-page-height});
  // min-height: calc(100vh - #{$nav-bar-height+$tabs-page-height});
  flex: 1;
  width: auto;
  padding: 16px;
  overflow: auto;
  background-color: #{$app-main-bg-color};
}
</style>
