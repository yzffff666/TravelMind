<template>
  <div class="empty">
    <div class="empty-visual">
      <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
        <circle cx="32" cy="28" r="18" stroke="currentColor" stroke-width="1.2" opacity="0.25"/>
        <path d="M32 10v36M14 28h36" stroke="currentColor" stroke-width="1" opacity="0.12"/>
        <path d="M32 16c-5.52 0-10 4.48-10 10 0 8 10 18 10 18s10-10 10-18c0-5.52-4.48-10-10-10z" stroke="currentColor" stroke-width="1.5"/>
        <circle cx="32" cy="26" r="3" stroke="currentColor" stroke-width="1.5"/>
        <path d="M20 52h24M24 48h16" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" opacity="0.2"/>
      </svg>
    </div>
    <p class="empty-title">你的行程将在这里呈现</p>
    <p class="empty-sub">在左侧输入旅行需求，AI 将为你生成详细行程</p>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  padding: 40px;
}

.empty-visual {
  color: var(--text-muted);
  opacity: 0.35;
  margin-bottom: 24px;
}

.empty-title {
  margin: 0;
  font-size: 16px;
  font-weight: 400;
  color: var(--text-sec);
  letter-spacing: -0.01em;
}

.empty-sub {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--text-muted);
  max-width: 280px;
}
</style>
