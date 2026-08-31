<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import AppInput from '@/components/AppInput.vue'
import { apiFetch } from '@/services/api'

const router = useRouter()
const name = ref('')
const error = ref('')
const loading = ref(false)

async function create() {
  error.value = ''
  if (!name.value.trim()) {
    error.value = 'Name is required'
    return
  }
  loading.value = true
  try {
    await apiFetch('/api/admin/tournaments', {
      method: 'POST',
      body: JSON.stringify({ name: name.value.trim() }),
    })
    router.push('/tournaments')
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Failed to create tournament'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="max-w-lg">
    <h1 class="mb-4 text-2xl font-bold">Create Tournament</h1>
    <form @submit.prevent="create" class="space-y-4">
      <AppInput v-model="name" label="Tournament name" placeholder="e.g. Spring Championship" :error="error" />
      <div class="flex gap-2">
        <button
          type="submit"
          :disabled="loading"
          class="rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          {{ loading ? 'Creating…' : 'Create Tournament' }}
        </button>
        <button
          type="button"
          class="rounded border border-zinc-300 bg-white px-4 py-2 text-sm hover:bg-zinc-50"
          @click="router.push('/tournaments')"
        >
          Cancel
        </button>
      </div>
    </form>
  </div>
</template>
