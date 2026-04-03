<template>
  <div class="error-state">
    <div class="error-visual">
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
        <circle cx="24" cy="24" r="20" stroke="currentColor" stroke-width="1.5" opacity="0.3"/>
        <path d="M24 14v12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
        <circle cx="24" cy="32" r="1.5" fill="currentColor"/>
      </svg>
    </div>
    <p class="error-title">{{ errorText || '请求失败' }}</p>
    <p class="error-sub">请检查网络连接或稍后重试</p>
    <div class="error-actions">
      <button class="btn-retry" @click="$emit('retry')">重试</button>
      <button class="btn-reset" @click="$emit('reset')">重置会话</button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ errorText: string }>()
defineEmits<{ retry: []; reset: [] }>()
</script>

<style scoped>
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  padding: 40px;
}

.error-visual {
  color: var(--error);
  opacity: 0.6;
  margin-bottom: 20px;
}

.error-title {
  margin: 0;
  font-size: 14px;
  font-weight: 500;
  color: #fca5a5;
  line-height: 1.6;
  max-width: 320px;
}

.error-sub {
  margin: 8px 0 0;
  font-size: 12.5px;
  color: var(--text-muted);
}

.error-actions {
  display: flex;
  gap: 10px;
  margin-top: 20px;
}

.btn-retry {
  padding: 8px 20px;
  font-size: 12.5px;
  font-weight: 500;
  font-family: inherit;
  color: #fff;
  background: var(--accent);
  border: none;
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: all 0.15s;
}

.btn-retry:hover {
  background: #0284c7;
  box-shadow: 0 4px 16px rgba(14, 165, 233, 0.25);
}

.btn-reset {
  padding: 8px 16px;
  font-size: 12.5px;
  font-weight: 500;
  font-family: inherit;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: all 0.15s;
}

.btn-reset:hover {
  color: var(--text-sec);
  border-color: var(--border-hover);
}
</style>
