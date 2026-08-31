<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import AppInput from '@/components/AppInput.vue'
import { apiFetch } from '@/services/api'

const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function create() {
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = 'Username and password are required'
    return
  }
  loading.value = true
  try {
    await apiFetch('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify({ username: username.value.trim(), password: password.value }),
    })
    router.push('/users')
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Failed to create user'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="max-w-lg">
    <h1 class="mb-4 text-2xl font-bold">Create User</h1>
    <form @submit.prevent="create" class="space-y-4">
      <AppInput v-model="username" label="Username" placeholder="username" :error="error" />
      <AppInput v-model="password" label="Password" type="password" placeholder="••••••••" />
      <div class="flex gap-2">
        <button
          type="submit"
          :disabled="loading"
          class="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {{ loading ? 'Creating…' : 'Create User' }}
        </button>
        <button
          type="button"
          class="rounded border border-zinc-300 bg-white px-4 py-2 text-sm hover:bg-zinc-50"
          @click="router.push('/users')"
        >
          Cancel
        </button>
      </div>
    </form>
  </div>
</template>
