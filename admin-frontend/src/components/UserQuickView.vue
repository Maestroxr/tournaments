<script setup lang="ts">
import { ref } from 'vue'
import Button from 'primevue/button'
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
    <Button
      v-if="userId !== null"
      :label="username"
      icon="bi bi-person-circle"
      link
      severity="contrast"
      :aria-expanded="open"
      @click.stop="show"
    />
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
          <Button icon="bi bi-x" text rounded severity="secondary" aria-label="Close user details" @click="open = false" />
        </span>
        <span class="block space-y-1 text-xs text-zinc-600">
          <span class="block"><span class="font-medium text-zinc-800">Email:</span> {{ user.email || 'No email' }}</span>
          <span class="block"><span class="font-medium text-zinc-800">Role:</span> {{ user.is_staff ? 'Staff' : 'User' }}</span>
          <span class="block"><span class="font-medium text-zinc-800">Status:</span> {{ user.is_active ? 'Active' : 'Inactive' }}</span>
        </span>
        <Button as="router-link" :to="`/users/${user.id}/edit`" label="Edit user" severity="contrast" class="w-full" />
      </span>
    </span>
  </span>
</template>
