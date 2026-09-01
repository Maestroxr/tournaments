<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import ToggleSwitch from 'primevue/toggleswitch'
import AppInput from '@/components/AppInput.vue'
import { apiFetch } from '@/services/api'

const router = useRouter()
const username = ref('')
const email = ref('')
const password1 = ref('')
const password2 = ref('')
const is_staff = ref(false)
const error = ref('')
const loading = ref(false)

const fieldErrors = computed(() => {
  const errs: Record<string, string> = {}
  if (!username.value.trim()) errs.username = 'Username required'
  else if (/^testuser-[0-9]+$/.test(username.value.trim())) errs.username = 'Username reserved'
  if (!password1.value) errs.password1 = 'Password required'
  if (password1.value !== password2.value) errs.password2 = 'Passwords must match'
  if (email.value && !/^\S+@\S+\.\S+$/.test(email.value)) errs.email = 'Invalid email'
  return errs
})
const hasErrors = computed(() => Object.keys(fieldErrors.value).length > 0)

async function create() {
  error.value = ''
  if (hasErrors.value) { error.value = Object.values(fieldErrors.value).join(' • '); return }
  loading.value = true
  try {
    await apiFetch('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify({
        username: username.value.trim(),
        email: email.value.trim(),
        password1: password1.value,
        password2: password2.value,
        is_staff: is_staff.value,
      }),
    })
    router.push('/users')
  } catch (e: unknown) {
    try { const b = JSON.parse((e as any).body || '{}'); error.value = b.errors ? JSON.stringify(b.errors) : b.detail || (e as Error).message } catch { error.value = e instanceof Error ? e.message : 'Failed' }
  } finally { loading.value = false }
}
</script>

<template>
  <div class="mx-auto w-full max-w-lg">
    <h1 class="mb-1 text-2xl font-bold text-black">Create User</h1>
    <p class="mb-4 text-sm text-zinc-600">Like tournament create — validated grid, black text, full API mapping.</p>
    <form @submit.prevent="create" class="space-y-4">
      <AppInput v-model="username" label="Username" placeholder="username" :error="fieldErrors.username || error" autocomplete="username" />
      <AppInput v-model="email" label="Email (optional)" placeholder="email@example.com" type="email" :error="fieldErrors.email" autocomplete="email" />
      <AppInput v-model="password1" label="Password" type="password" placeholder="••••••••" :error="fieldErrors.password1" autocomplete="new-password" />
      <AppInput v-model="password2" label="Password confirmation" type="password" placeholder="••••••••" :error="fieldErrors.password2" autocomplete="new-password" />
      <label class="flex items-center gap-3 text-sm text-black"><ToggleSwitch v-model="is_staff" /> Staff (admin access)</label>

      <div class="rounded-lg border border-zinc-200 bg-zinc-50 p-3 text-xs text-zinc-600">
        Preview: <span class="font-medium text-black">{{ username || '—' }}</span> • {{ email || 'no email' }} • {{ is_staff ? 'staff' : 'user' }}
      </div>

      <div class="flex gap-2">
        <Button type="submit" :label="loading ? 'Creating...' : 'Create User'" :loading="loading" severity="info" />
        <Button label="Cancel" severity="secondary" outlined @click="router.push('/users')" />
      </div>
    </form>
  </div>
</template>
