<script setup lang="ts">
</script>

<template>
  <router-view></router-view>
</template>

<style>
*, *::before, *::after {
  box-sizing: border-box;
}

html, body {
  margin: 0;
  padding: 0;
  height: 100%;
  overflow: hidden;
  background: #0a0a0a;
}

#app {
  height: 100%;
  font-family: 'Inter', 'Noto Sans SC', system-ui, -apple-system, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
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
  background: #0a0a0a;
}

.loading-spinner {
  width: 36px;
  height: 36px;
  border: 2px solid rgba(255,255,255,0.06);
  border-top-color: #999;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style> 