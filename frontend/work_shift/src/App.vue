<script setup lang="ts">
// App.vue
// vue-routerは使わず、選択中の画面IDをstateで持ってv-ifで切り替える簡易実装。
import { ref } from 'vue';
import Sidebar from './components/Sidebar.vue';
import type { ScreenId } from './components/Sidebar.vue';
import ShiftTableContainer from './components/ShiftTableContainer.vue';
import GroupeCrud from './components/GroupeCrud.vue';
import StaffCrud from './components/StaffCrud.vue';
import SpotWorkerCrud from './components/SpotWorkerCrud.vue';
import WorkShiftTypeCrud from './components/WorkShiftTypeCrud.vue';

const activeScreen = ref<ScreenId>('shift');
</script>

<template>
  <div class="app-root">
    <Sidebar :active-screen="activeScreen" @navigate="(s) => (activeScreen = s)" />
    <main class="main-content">
      <ShiftTableContainer v-if="activeScreen === 'shift'" />
      <GroupeCrud v-else-if="activeScreen === 'groupe'" />
      <StaffCrud v-else-if="activeScreen === 'staff'" />
      <SpotWorkerCrud v-else-if="activeScreen === 'spotworker'" />
      <WorkShiftTypeCrud v-else-if="activeScreen === 'workshifttype'" />
    </main>
  </div>
</template>

<style>
body {
  margin: 0;
}
.app-root {
  display: flex;
  min-height: 100vh;
}
.main-content {
  flex: 1;
  min-width: 0;
}
</style>
