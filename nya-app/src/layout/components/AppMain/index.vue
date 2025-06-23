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
  flex: 1;
  width: auto;
  overflow: auto;
  background-color: #{$app-main-bg-color};
}
</style>
