<script setup lang="ts">
import SideNavigationBar from './components/SideNavigationBar/index.vue';
import NavBar from './components/Navbar/index.vue';
import AppMain from './components/AppMain/index.vue';
</script>

<template>
  <div class="app-wrapper">
    <!-- Sidebar -->
    <SideNavigationBar />
    <!-- Content -->
    <div class="main-container">
      <NavBar />
      <AppMain />
    </div>
  </div>
</template>

<style lang="scss" scoped>
.app-wrapper {
  display: flex;
  width: 100%;
  height: 100%;
  overflow: hidden;
  .main-container {
    flex: 1;
    width: 100%;
    height: 100%;
    overflow: hidden;
  }
}
</style>