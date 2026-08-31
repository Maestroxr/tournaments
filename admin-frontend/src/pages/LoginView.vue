<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/services/api'
import AppInput from '@/components/AppInput.vue'
import AppAlert from '@/components/AppAlert.vue'

const auth = useAuthStore()
const router = useRouter()
const username = ref('')
const password = ref('')
const usernameError = ref('')
const passwordError = ref('')
const alertMessage = ref('')

function parseApiError(e: unknown): string {
  if (e instanceof ApiError) {
    try {
      const data = JSON.parse(e.body) as Record<string, unknown>
      if (typeof data.detail === 'string') {
        if (data.detail.toLowerCase().includes('invalid')) return 'Username or password is incorrect'
        return data.detail
      }
      if (Array.isArray(data.non_field_errors)) return String(data.non_field_errors[0])
      // field errors handled separately
      return e.body
    } catch {
      if (e.body.toLowerCase().includes('invalid')) return 'Username or password is incorrect'
      return e.body
    }
  }
  if (e instanceof Error) return e.message
  return 'Login failed'
}

async function login() {
  usernameError.value = ''
  passwordError.value = ''
  alertMessage.value = ''

  if (!username.value.trim()) usernameError.value = 'Username is not correct'
  if (!password.value) passwordError.value = 'Password is not correct'
  if (usernameError.value || passwordError.value) return

  try {
    await auth.login(username.value.trim(), password.value)
    router.push('/dashboard')
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
    <h1 class="mb-4 text-xl font-bold text-black">Admin Login</h1>
    <AppAlert v-if="alertMessage" type="error" :message="alertMessage" dismissible class="mb-4" @close="alertMessage = ''" />
    <form @submit.prevent="login" class="space-y-3">
      <AppInput v-model="username" label="Username" placeholder="username" autocomplete="username" :error="usernameError" @keydown="login" />
      <AppInput v-model="password" label="Password" type="password" placeholder="password" autocomplete="current-password" :error="passwordError" @keydown="login" />
      <button type="submit" class="w-full rounded bg-dark px-4 py-2 text-sm font-medium text-white hover:bg-dark-hover">
        Login
      </button>
    </form>
  </div>
</template>
