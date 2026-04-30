<script setup lang="ts">
</script>

<template>
  <router-view></router-view>
</template>

<style>
#app {
  min-height: 100vh;
  min-height: 100dvh;
}

.loading-screen {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--tm-color-bg);
}

.loading-spinner {
  width: 36px;
  height: 36px;
  border: 2px solid var(--tm-color-border);
  border-top-color: var(--tm-color-cyan);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style> 