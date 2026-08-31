<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppInput from '@/components/AppInput.vue'
import { apiFetch } from '@/services/api'

const route = useRoute()
const router = useRouter()
const id = route.params.id as string

const username = ref('')
const email = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const fetching = ref(true)

interface UserDetail {
  id: number
  username: string
  email?: string
}

onMounted(async () => {
  try {
    const data = await apiFetch<UserDetail>(`/api/admin/users/${id}`)
    username.value = data.username
    email.value = data.email ?? ''
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Failed to load user'
  } finally {
    fetching.value = false
  }
})

async function save() {
  error.value = ''
  if (!username.value.trim()) {
    error.value = 'Username is required'
    return
  }
  loading.value = true
  try {
    const payload: Record<string, string> = { username: username.value.trim(), email: email.value.trim() }
    if (password.value) payload.password = password.value
    await apiFetch(`/api/admin/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
    router.push('/users')
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Failed to update user'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="max-w-lg">
    <h1 class="mb-4 text-2xl font-bold">Edit User</h1>
    <p v-if="fetching" class="text-sm text-zinc-500">Loading…</p>
    <form v-else @submit.prevent="save" class="space-y-4">
      <AppInput v-model="username" label="Username" placeholder="username" :error="error" />
      <AppInput v-model="email" label="Email" placeholder="email@example.com" type="email" />
      <AppInput v-model="password" label="New password (leave blank to keep)" type="password" placeholder="••••••••" />
      <div class="flex gap-2">
        <button
          type="submit"
          :disabled="loading"
          class="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {{ loading ? 'Saving…' : 'Save' }}
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
