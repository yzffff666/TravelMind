<template>
  <div class="login-container">
    <div class="login-orb login-orb--left" aria-hidden="true" />
    <div class="login-orb login-orb--right" aria-hidden="true" />
    <div class="login-locale"><LocaleSwitch /></div>

    <GlassCard class="login-box">
      <div class="brand-block">
        <div class="logo">
          <img src="../assets/deepseek.svg" alt="TravelMind" />
        </div>
        <StatusBadge tone="info">{{ t('auth.badge') }}</StatusBadge>
      </div>

      <div class="title-group">
        <h1 class="login-title">{{ activeTab === 'login' ? t('auth.loginTitle') : t('auth.registerTitle') }}</h1>
        <p class="login-subtitle">
          {{ activeTab === 'login' ? t('auth.loginSubtitle') : t('auth.registerSubtitle') }}
        </p>
      </div>

      <div class="form-container">
        <div v-if="errorMessage('general')" class="general-error">
          {{ errorMessage('general') }}
        </div>

        <BaseInput
          v-if="activeTab === 'register'"
          v-model="form.username"
          :label="t('auth.username')"
          :placeholder="t('auth.usernamePlaceholder')"
          autocomplete="username"
          :error="errorMessage('username')"
        />

        <BaseInput
          v-model="form.email"
          :label="t('auth.email')"
          type="email"
          placeholder="you@example.com"
          autocomplete="email"
          :error="errorMessage('email')"
        />

        <BaseInput
          v-model="form.password"
          :label="t('auth.password')"
          type="password"
          :placeholder="t('auth.passwordPlaceholder')"
          autocomplete="current-password"
          :error="errorMessage('password')"
        />

        <BaseInput
          v-if="activeTab === 'register'"
          v-model="form.confirmPassword"
          :label="t('auth.confirmPassword')"
          type="password"
          :placeholder="t('auth.confirmPasswordPlaceholder')"
          autocomplete="new-password"
        />

        <div v-if="activeTab === 'register'" class="agreement">
          <input type="checkbox" v-model="form.agreement" id="agreement" />
          <label for="agreement">
            {{ t('auth.agreementPrefix') }} <a href="#" @click.prevent="showTerms">{{ t('auth.terms') }}</a>
            {{ t('auth.and') }} <a href="#" @click.prevent="showPrivacy">{{ t('auth.privacy') }}</a>
          </label>
        </div>

        <BaseButton class="submit-btn" size="lg" :loading="isSubmitting" :disabled="!isFormValid" @click="handleSubmit">
          {{ activeTab === 'login' ? t('auth.login') : t('auth.register') }}
        </BaseButton>

        <div class="register-link">
          {{ activeTab === 'login' ? t('auth.noAccount') : t('auth.hasAccount') }}
          <a href="#" @click.prevent="handleTabChange">
            {{ activeTab === 'login' ? t('auth.registerNow') : t('auth.backToLogin') }}
          </a>
        </div>

        <div class="other-login" v-if="activeTab === 'login'">
          <div class="divider">
            <span>{{ t('auth.otherLogin') }}</span>
          </div>
          <BaseButton class="wechat-btn" variant="secondary" @click="handleWechatLogin">
            <img src="../assets/wechat.svg" alt="WeChat" />
            {{ t('auth.wechat') }}
          </BaseButton>
        </div>
      </div>
    </GlassCard>
    <MessageBox
      v-if="showSuccessMessage"
      :title="t('auth.registerSuccess')"
      :message="t('auth.registerSuccessMessage')"
      type="success"
      :buttonText="t('auth.goToLogin')"
      @confirm="handleSuccessConfirm"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { AuthService } from '../services/api'
import MessageBox from '../components/MessageBox.vue'
import { useConversationStore } from '../stores/conversation'
import { BaseButton, BaseInput, GlassCard, LocaleSwitch, StatusBadge } from '../components/ui'

const router = useRouter()
const { t } = useI18n()
const conversationStore = useConversationStore()
const activeTab = ref('login')

const form = ref({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
  agreement: false
})

type ErrorField = 'username' | 'email' | 'password' | 'general'
type FormError = { key: string } | { text: string } | null

const emptyErrors = (): Record<ErrorField, FormError> => ({
  username: null,
  email: null,
  password: null,
  general: null,
})

const errors = ref<Record<ErrorField, FormError>>(emptyErrors())
const errorMessage = (field: ErrorField) => {
  const error = errors.value[field]
  if (!error) return ''
  return 'key' in error ? t(error.key) : error.text
}

const showSuccessMessage = ref(false)
const isSubmitting = ref(false)

const validateRules = {
  username: {
    pattern: /^[a-zA-Z0-9_]{4,16}$/,
    messageKey: 'auth.validation.username'
  },
  email: {
    pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
    messageKey: 'auth.validation.email'
  },
  password: {
    pattern: /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$/,
    messageKey: 'auth.validation.password'
  }
}

const validate = (field: 'username' | 'email' | 'password', value: string) => {
  if (!value) {
    const key = field === 'username'
      ? 'auth.validation.requiredUsername'
      : field === 'email'
        ? 'auth.validation.requiredEmail'
        : 'auth.validation.requiredPassword'
    errors.value[field] = { key }
    return false
  }
  if (!validateRules[field].pattern.test(value)) {
    errors.value[field] = { key: validateRules[field].messageKey }
    return false
  }
  errors.value[field] = null
  return true
}

const isFormValid = computed(() => {
  if (activeTab.value === 'login') {
    return Boolean(
      form.value.email &&
      validateRules.email.pattern.test(form.value.email) &&
      form.value.password
    )
  }

  return Boolean(
    form.value.username &&
    form.value.email &&
    form.value.password &&
    form.value.confirmPassword &&
    form.value.password === form.value.confirmPassword &&
    form.value.agreement &&
    validateRules.username.pattern.test(form.value.username) &&
    validateRules.email.pattern.test(form.value.email) &&
    validateRules.password.pattern.test(form.value.password)
  )
})

const clearErrors = () => {
  errors.value = emptyErrors()
}

const handleSubmit = async () => {
  if (activeTab.value === 'register' && !form.value.agreement) {
    errors.value.general = { key: 'auth.validation.agreement' }
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
      errors.value.general = { key: 'auth.validation.credentials' }
    } else if (error.response?.data?.detail) {
      const detail = error.response.data.detail
      if (typeof detail === 'string') {
        errors.value.general = { text: detail }
      } else if (Array.isArray(detail)) {
        detail.forEach(err => {
          const field = err.loc[1]
          if (typeof field === 'string' && field in errors.value) {
            errors.value[field as ErrorField] = { text: err.msg }
          }
        })
      }
    } else {
      errors.value.general = { key: 'auth.validation.generic' }
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
  clearErrors()
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

.login-locale {
  position: absolute;
  z-index: 2;
  top: var(--tm-space-5);
  right: var(--tm-space-5);
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
