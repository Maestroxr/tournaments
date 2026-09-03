<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ApiError, formatApiError } from '@/services/api'
import Button from 'primevue/button'
import AppInput from '@/components/AppInput.vue'
import AppAlert from '@/components/AppAlert.vue'
import { useI18n } from '@/i18n'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const usernameError = ref('')
const passwordError = ref('')
const alertMessage = ref('')
const { t } = useI18n()

if (route.query.reason === 'admin-required') {
  alertMessage.value = t('common.adminRequired')
}

function parseApiError(e: unknown): string {
  if (e instanceof ApiError) {
    try {
      const data = JSON.parse(e.body) as Record<string, unknown>
      if (typeof data.detail === 'string') {
        if (data.detail.toLowerCase().includes('invalid')) return t('common.invalidLogin')
        return data.detail
      }
      if (Array.isArray(data.non_field_errors)) return String(data.non_field_errors[0])
      // field errors handled separately
      return formatApiError(e)
    } catch {
      if (e.body.toLowerCase().includes('invalid')) return t('common.invalidLogin')
      return formatApiError(e)
    }
  }
  if (e instanceof Error) return e.message
  return t('common.loginFailed')
}

async function login() {
  usernameError.value = ''
  passwordError.value = ''
  alertMessage.value = ''

  if (!username.value.trim()) usernameError.value = t('common.usernameInvalid')
  if (!password.value) passwordError.value = t('common.passwordInvalid')
  if (usernameError.value || passwordError.value) return

  try {
    await auth.login(username.value.trim(), password.value)
    if (!auth.isAdmin) {
      alertMessage.value = t('common.noAdminAccess')
      return
    }
    const next = typeof route.query.next === 'string' ? route.query.next : '/dashboard'
    router.push(next)
  } catch (e: unknown) {
    // field-specific errors from API
    if (e instanceof ApiError) {
      try {
        const data = JSON.parse(e.body) as Record<string, unknown>
        if (Array.isArray(data.username)) usernameError.value = String(data.username[0])
        if (Array.isArray(data.password)) passwordError.value = String(data.password[0])
        if (usernameError.value || passwordError.value) return
      } catch {
        /* fall through to alert */
      }
    }
    alertMessage.value = parseApiError(e)
  }
}
</script>
<template>
  <div class="mx-auto max-w-sm">
    <h1 class="mb-4 text-xl font-bold text-black">{{ t('nav.brand') }} {{ t('common.login') }}</h1>
    <AppAlert v-if="alertMessage" type="error" :message="alertMessage" dismissible class="mb-4" @close="alertMessage = ''" />
    <form @submit.prevent="login" class="space-y-3">
      <AppInput v-model="username" :label="t('users.username')" :placeholder="t('users.username')" autocomplete="username" :error="usernameError" @keydown="login" />
      <AppInput v-model="password" :label="t('users.password')" type="password" :placeholder="t('users.password')" autocomplete="current-password" :error="passwordError" @keydown="login" />
      <Button type="submit" :label="t('common.login')" severity="contrast" class="w-full" />
    </form>
  </div>
</template>
