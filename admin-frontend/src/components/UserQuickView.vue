<script setup lang="ts">
import { ref } from 'vue'
import { apiFetch } from '@/services/api'
import type { AdminUserSummary } from '@/types/user'

const props = defineProps<{
  userId: number | null
  username: string
}>()

const open = ref(false)
const loading = ref(false)
const error = ref('')
const user = ref<AdminUserSummary | null>(null)

let closeTimer: ReturnType<typeof setTimeout> | null = null

async function show() {
  if (props.userId === null) return
  if (closeTimer) {
    clearTimeout(closeTimer)
    closeTimer = null
  }
  open.value = true
  if (user.value || loading.value) return
  loading.value = true
  error.value = ''
  try {
    user.value = await apiFetch<AdminUserSummary>(`/api/admin/users/${props.userId}`)
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : 'Failed to load user'
  } finally {
    loading.value = false
  }
}

function scheduleClose() {
  if (closeTimer) clearTimeout(closeTimer)
  closeTimer = setTimeout(() => {
    open.value = false
    closeTimer = null
  }, 150)
}
</script>

<template>
  <span class="relative inline-flex" @mouseenter="show" @mouseleave="scheduleClose" @focusin="show" @focusout="scheduleClose">
    <button
      v-if="userId !== null"
      type="button"
      class="inline-flex items-center gap-1 font-medium text-zinc-900 hover:text-blue-700 hover:underline"
      :aria-expanded="open"
      @click.stop="show"
    >
      <i class="bi bi-person-circle text-zinc-400" aria-hidden="true"></i>
      {{ username }}
    </button>
    <span v-else class="inline-flex items-center gap-1 font-medium text-zinc-700">
      <i class="bi bi-person text-zinc-400" aria-hidden="true"></i>
      {{ username }}
    </span>

    <span
      v-if="open"
      class="absolute left-0 top-full z-30 mt-2 w-64 rounded-xl border border-zinc-200 bg-white p-4 text-left shadow-lg"
      @click.stop
    >
      <span v-if="loading" class="block text-sm text-zinc-500">Loading user…</span>
      <span v-else-if="error" class="block text-sm text-red-600">{{ error }}</span>
      <span v-else-if="user" class="block space-y-3">
        <span class="flex items-start justify-between gap-2">
          <span>
            <span class="block font-semibold text-black">{{ user.username }}</span>
            <span class="block text-xs text-zinc-500">User #{{ user.id }}</span>
          </span>
          <button type="button" class="text-zinc-400 hover:text-black" aria-label="Close user details" @click="open = false">×</button>
        </span>
        <span class="block space-y-1 text-xs text-zinc-600">
          <span class="block"><span class="font-medium text-zinc-800">Email:</span> {{ user.email || 'No email' }}</span>
          <span class="block"><span class="font-medium text-zinc-800">Role:</span> {{ user.is_staff ? 'Staff' : 'User' }}</span>
          <span class="block"><span class="font-medium text-zinc-800">Status:</span> {{ user.is_active ? 'Active' : 'Inactive' }}</span>
        </span>
        <RouterLink
          :to="`/users/${user.id}/edit`"
          class="block rounded-lg bg-zinc-900 px-3 py-2 text-center text-sm font-medium text-white hover:bg-black"
        >
          Edit user
        </RouterLink>
      </span>
    </span>
  </span>
</template>
