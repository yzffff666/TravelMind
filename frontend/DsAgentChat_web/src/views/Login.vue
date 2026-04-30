<template>
  <div class="login-container">
    <div class="login-orb login-orb--left" aria-hidden="true" />
    <div class="login-orb login-orb--right" aria-hidden="true" />

    <GlassCard class="login-box">
      <div class="brand-block">
        <div class="logo">
          <img src="../assets/deepseek.svg" alt="TravelMind" />
        </div>
        <StatusBadge tone="info">AI Travel Copilot</StatusBadge>
      </div>

      <div class="title-group">
        <h1 class="login-title">{{ activeTab === 'login' ? '欢迎回来' : '创建 TravelMind 账号' }}</h1>
        <p class="login-subtitle">
          {{ activeTab === 'login' ? '继续规划你的下一段旅程。' : '用对话、证据和地图一起完成旅行计划。' }}
        </p>
      </div>

      <div class="form-container">
        <div v-if="errors.general" class="general-error">
          {{ errors.general }}
        </div>

        <BaseInput
          v-if="activeTab === 'register'"
          v-model="form.username"
          label="用户名"
          placeholder="4-16 位字母、数字或下划线"
          autocomplete="username"
          :error="errors.username"
        />

        <BaseInput
          v-model="form.email"
          label="邮箱"
          type="email"
          placeholder="you@example.com"
          autocomplete="email"
          :error="errors.email"
        />

        <BaseInput
          v-model="form.password"
          label="密码"
          type="password"
          placeholder="请输入密码"
          autocomplete="current-password"
          :error="errors.password"
        />

        <BaseInput
          v-if="activeTab === 'register'"
          v-model="form.confirmPassword"
          label="确认密码"
          type="password"
          placeholder="再次输入密码"
          autocomplete="new-password"
        />

        <div class="agreement">
          <input type="checkbox" v-model="form.agreement" id="agreement" />
          <label for="agreement">
            我已同意 <a href="#" @click.prevent="showTerms">用户协议</a> 与 <a href="#" @click.prevent="showPrivacy">隐私政策</a>
          </label>
        </div>

        <BaseButton class="submit-btn" size="lg" :loading="isSubmitting" :disabled="!isFormValid" @click="handleSubmit">
          {{ activeTab === 'login' ? '登录' : '注册' }}
        </BaseButton>

        <div class="register-link">
          {{ activeTab === 'login' ? '还没有账号？' : '已有账号？' }}
          <a href="#" @click.prevent="handleTabChange">
            {{ activeTab === 'login' ? '立即注册' : '返回登录' }}
          </a>
        </div>

        <div class="other-login" v-if="activeTab === 'login'">
          <div class="divider">
            <span>其他登录方式</span>
          </div>
          <BaseButton class="wechat-btn" variant="secondary" @click="handleWechatLogin">
            <img src="../assets/wechat.svg" alt="WeChat" />
            使用微信自动登录
          </BaseButton>
        </div>
      </div>
    </GlassCard>
    <MessageBox
      v-if="showSuccessMessage"
      title="注册成功"
      message="请使用注册的账号登录"
      type="success"
      buttonText="去登录"
      @confirm="handleSuccessConfirm"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { AuthService } from '../services/api'
import MessageBox from '../components/MessageBox.vue'
import { useConversationStore } from '../stores/conversation'
import { BaseButton, BaseInput, GlassCard, StatusBadge } from '../components/ui'

const router = useRouter()
const conversationStore = useConversationStore()
const activeTab = ref('login')

const form = ref({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
  agreement: false
})

const errors = ref({
  username: '',
  email: '',
  password: '',
  general: ''
})

const showSuccessMessage = ref(false)
const isSubmitting = ref(false)

const validateRules = {
  username: {
    pattern: /^[a-zA-Z0-9_]{4,16}$/,
    message: '用户名必须是4-16位字母、数字或下划线'
  },
  email: {
    pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
    message: '请输入有效的邮箱地址'
  },
  password: {
    pattern: /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[a-zA-Z\d]{8,}$/,
    message: '密码必须包含大小写字母和数字，至少8位'
  }
}

const validate = (field: 'username' | 'email' | 'password', value: string) => {
  if (!value) {
    errors.value[field] = `请输入${field === 'username' ? '用户名' : field === 'email' ? '邮箱' : '密码'}`
    return false
  }
  if (!validateRules[field].pattern.test(value)) {
    errors.value[field] = validateRules[field].message
    return false
  }
  errors.value[field] = ''
  return true
}

const isFormValid = computed(() => {
  if (activeTab.value === 'login') {
    return form.value.email && 
           form.value.password &&
           form.value.agreement &&
           validate('email', form.value.email) &&
           validate('password', form.value.password)
  } else {
    return form.value.username && 
           form.value.email &&
           form.value.password && 
           form.value.confirmPassword && 
           form.value.password === form.value.confirmPassword &&
           form.value.agreement &&
           validate('username', form.value.username) &&
           validate('email', form.value.email) &&
           validate('password', form.value.password)
  }
})

const clearErrors = () => {
  errors.value = {
    username: '',
    email: '',
    password: '',
    general: ''
  }
}

const handleSubmit = async () => {
  if (!form.value.agreement) {
    errors.value.general = '请先同意用户协议和隐私政策'
    return
  }
  
  if (!isFormValid.value || isSubmitting.value) return
  
  clearErrors()
  isSubmitting.value = true
  
  try {
    if (activeTab.value === 'register') {
      await AuthService.register({
        username: form.value.username,
        email: form.value.email,
        password: form.value.password
      })
      showSuccessMessage.value = true
      router.replace('/login')
      activeTab.value = 'login'
    } else {
      const response = await AuthService.login({
        email: form.value.email,
        password: form.value.password
      })
      localStorage.setItem('token', response.access_token)
      const userInfo = await AuthService.getUserInfo()
      localStorage.setItem('user_id', userInfo.id.toString())
      await conversationStore.createNewConversation()
      router.push('/')
    }
  } catch (error: any) {
    if (error.response?.status === 401) {
      errors.value.general = '邮箱或密码错误'
    } else if (error.response?.data?.detail) {
      const detail = error.response.data.detail
      if (typeof detail === 'string') {
        errors.value.general = detail
      } else if (Array.isArray(detail)) {
        detail.forEach(err => {
          const field = err.loc[1]
          errors.value[field as keyof typeof errors.value] = err.msg
        })
      }
    } else {
      errors.value.general = '发生错误，请稍后重试'
    }
  } finally {
    isSubmitting.value = false
  }
}

const handleSuccessConfirm = () => {
  showSuccessMessage.value = false
  activeTab.value = 'login'
  form.value = {
    username: form.value.username,
    email: form.value.email,
    password: '',
    confirmPassword: '',
    agreement: false
  }
}

const handleWechatLogin = () => {
  // TODO: 微信登录逻辑
}

const showTerms = () => {
  // TODO: 显示用户协议
}

const showPrivacy = () => {
  // TODO: 显示隐私政策
}

const handleTabChange = () => {
  const newTab = activeTab.value === 'login' ? 'register' : 'login'
  activeTab.value = newTab
  // 更新 URL，但不触发新的导航
  router.replace(`/${newTab}`)
}

onMounted(() => {
  // 根据当前路由设置正确的标签
  activeTab.value = router.currentRoute.value.path === '/register' ? 'register' : 'login'
})

watch(() => form.value.username, (val) => {
  if (activeTab.value === 'register' && val) {
    validate('username', val)
  }
})

watch(() => form.value.email, (val) => {
  if (val) validate('email', val)
})

watch(() => form.value.password, (val) => {
  if (val) validate('password', val)
})
</script>

<style scoped>
.login-container {
  position: relative;
  min-height: 100vh;
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: var(--tm-space-6);
  overflow: hidden;
}

.login-container::before {
  content: '';
  position: absolute;
  inset: 0;
  background:
    linear-gradient(rgba(148, 163, 184, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.04) 1px, transparent 1px);
  background-size: 42px 42px;
  mask-image: radial-gradient(circle at center, black, transparent 72%);
  pointer-events: none;
}

.login-orb {
  position: absolute;
  width: 320px;
  height: 320px;
  border-radius: 50%;
  filter: blur(24px);
  opacity: 0.28;
  pointer-events: none;
}

.login-orb--left {
  left: -120px;
  bottom: 10%;
  background: var(--tm-color-indigo);
}

.login-orb--right {
  top: 8%;
  right: -100px;
  background: var(--tm-color-cyan);
}

.login-box {
  position: relative;
  z-index: 1;
  width: min(100%, 460px);
  padding: var(--tm-space-8);
}

.brand-block,
.title-group {
  display: grid;
  justify-items: center;
  gap: var(--tm-space-3);
}

.logo {
  width: 64px;
  height: 64px;
  display: grid;
  place-items: center;
  border: 1px solid var(--tm-color-border-strong);
  border-radius: var(--tm-radius-2xl);
  background: rgba(255, 255, 255, 0.08);
  box-shadow: var(--tm-shadow-glow);
}

.logo img {
  width: 38px;
  height: 38px;
}

.title-group {
  margin-top: var(--tm-space-8);
  margin-bottom: var(--tm-space-8);
}

.login-title {
  margin: 0;
  color: var(--tm-color-text-primary);
  font-size: clamp(28px, 5vw, 36px);
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: var(--tm-line-height-tight);
  text-align: center;
}

.login-subtitle {
  margin: 0;
  color: var(--tm-color-text-secondary);
  font-size: var(--tm-font-size-sm);
  line-height: var(--tm-line-height-normal);
  text-align: center;
}

.form-container {
  display: grid;
  gap: var(--tm-space-4);
}

.register-link {
  text-align: center;
  color: var(--tm-color-text-muted);
  font-size: var(--tm-font-size-sm);
}

.register-link a {
  color: var(--tm-color-cyan);
  font-weight: 700;
  text-decoration: none;
  margin-left: var(--tm-space-2);
}

.register-link a:hover,
.agreement a:hover {
  text-decoration: underline;
}

.agreement {
  display: flex;
  align-items: flex-start;
  gap: var(--tm-space-2);
  color: var(--tm-color-text-muted);
  font-size: var(--tm-font-size-sm);
  line-height: var(--tm-line-height-normal);
}

.agreement input {
  width: 18px;
  height: 18px;
  margin-top: 2px;
  accent-color: var(--tm-color-primary);
}

.agreement a {
  color: var(--tm-color-cyan);
  text-decoration: none;
}

.submit-btn {
  width: 100%;
}

.other-login {
  display: grid;
  gap: var(--tm-space-4);
  margin-top: var(--tm-space-2);
}

.divider {
  display: flex;
  align-items: center;
  color: var(--tm-color-text-muted);
  font-size: var(--tm-font-size-xs);
}

.divider::before,
.divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--tm-color-border);
  margin: 0 var(--tm-space-4);
}

.wechat-btn {
  width: 100%;
}

.wechat-btn img {
  width: 24px;
  height: 24px;
}

.general-error {
  padding: var(--tm-space-3) var(--tm-space-4);
  border: 1px solid rgba(251, 113, 133, 0.32);
  border-radius: var(--tm-radius-lg);
  background: rgba(251, 113, 133, 0.12);
  color: var(--tm-color-danger);
  font-size: var(--tm-font-size-sm);
  text-align: center;
}

@media (max-width: 560px) {
  .login-container {
    padding: var(--tm-space-4);
  }

  .login-box {
    padding: var(--tm-space-6);
  }
}
</style> 