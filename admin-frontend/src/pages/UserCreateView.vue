<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import ToggleSwitch from 'primevue/toggleswitch'
import AppInput from '@/components/AppInput.vue'
import AppAlert from '@/components/AppAlert.vue'
import { apiFetch, apiFieldErrors, formatApiError } from '@/services/api'

const router = useRouter()
const username = ref('')
const email = ref('')
const password1 = ref('')
const password2 = ref('')
const is_staff = ref(false)
const error = ref('')
const submitted = ref(false)
const loading = ref(false)
const serverFieldErrors = ref<Record<string, string>>({})

const clientFieldErrors = computed(() => {
  const errs: Record<string, string> = {}
  if (!username.value.trim()) errs.username = 'Username required.'
  else if (/^testuser-[0-9]+$/.test(username.value.trim())) errs.username = 'This username is reserved.'
  if (!password1.value) errs.password1 = 'Password required.'
  if (password1.value !== password2.value) errs.password2 = 'Passwords must match.'
  if (email.value && !/^\S+@\S+\.\S+$/.test(email.value)) errs.email = 'Enter a valid email address.'
  return errs
})
const visibleClientErrors = computed(() => submitted.value ? clientFieldErrors.value : {})
const fieldErrors = computed(() => ({ ...serverFieldErrors.value, ...visibleClientErrors.value }))
const hasErrors = computed(() => Object.keys(clientFieldErrors.value).length > 0)

function clearServerError(field: string) {
  if (!serverFieldErrors.value[field]) return
  const next = { ...serverFieldErrors.value }
  delete next[field]
  serverFieldErrors.value = next
}

async function create() {
  submitted.value = true
  error.value = ''
  serverFieldErrors.value = {}
  if (hasErrors.value) { error.value = 'Review the highlighted fields before creating the user.'; return }
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
  } catch (caught: unknown) {
    serverFieldErrors.value = apiFieldErrors(caught)
    error.value = Object.keys(serverFieldErrors.value).length
      ? 'Review the highlighted fields before creating the user.'
      : formatApiError(caught)
  } finally { loading.value = false }
}
</script>

<template>
  <div class="mx-auto w-full max-w-lg">
    <h1 class="mb-1 text-2xl font-bold text-black">Create User</h1>
    <p class="mb-4 text-sm text-zinc-600">Like tournament create — validated grid, black text, full API mapping.</p>
    <AppAlert v-if="error" class="mb-5" type="error" :message="error" dismissible @close="error = ''" />
    <form @submit.prevent="create" class="space-y-4">
      <div class="grid gap-4 sm:grid-cols-2">
        <AppInput v-model="username" label="Username" placeholder="username" :error="fieldErrors.username" autocomplete="username" @update:model-value="clearServerError('username')" />
        <AppInput v-model="email" label="Email (optional)" placeholder="email@example.com" type="email" :error="fieldErrors.email" autocomplete="email" @update:model-value="clearServerError('email')" />
        <AppInput v-model="password1" label="Password" type="password" placeholder="Password" :error="fieldErrors.password1" autocomplete="new-password" @update:model-value="clearServerError('password1')" />
        <AppInput v-model="password2" label="Password confirmation" type="password" placeholder="Confirm password" :error="fieldErrors.password2" autocomplete="new-password" @update:model-value="clearServerError('password2')" />
      </div>
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
