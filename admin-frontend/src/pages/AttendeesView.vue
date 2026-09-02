<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { apiFetch, formatApiError } from '@/services/api'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Tag from 'primevue/tag'
import AppAlert from '@/components/AppAlert.vue'

interface Participant {
  id: number
  name: string
  user_id: number | null
}

interface AvailableUser {
  id: number
  username: string
  email?: string
}

interface AttendeesResponse {
  participants: Participant[]
  available: AvailableUser[]
}

const route = useRoute()
const id = String(route.params.id)
const loading = ref(true)
const error = ref('')
const participants = ref<Participant[]>([])
const available = ref<AvailableUser[]>([])
const q = ref('')
const newName = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const qs = q.value.trim() ? `?q=${encodeURIComponent(q.value.trim())}` : ''
    const data = await apiFetch<AttendeesResponse>(`/api/admin/tournaments/${id}/attendees${qs}`)
    participants.value = data.participants
    available.value = data.available
  } catch (e: unknown) { error.value = formatApiError(e) }
  finally { loading.value = false }
}
onMounted(load)

async function addUser(uid: number) {
  try { await apiFetch(`/api/admin/tournaments/${id}/attendees`, { method: 'POST', body: JSON.stringify({ user_id: uid }) }); await load() } catch (e: unknown) { error.value = formatApiError(e) }
}
async function addVirtual() {
  if (!newName.value.trim()) return
  try { await apiFetch(`/api/admin/tournaments/${id}/attendees`, { method: 'POST', body: JSON.stringify({ name: newName.value.trim() }) }); newName.value=''; await load() } catch (e: unknown) { error.value = formatApiError(e) }
}
async function remove(pid: number) {
  try { await apiFetch(`/api/admin/tournaments/${id}/attendees?participant_id=${pid}`, { method: 'DELETE' }); await load() } catch (e: unknown) { error.value = formatApiError(e) }
}
</script>

<template>
  <div class="mx-auto w-full max-w-4xl">
    <header class="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <p class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Tournament #{{ id }}</p>
        <h1 class="text-2xl font-bold text-black">Manage attendees</h1>
        <p class="mt-1 text-sm text-zinc-600">Registration list and eligible users.</p>
      </div>
      <RouterLink :to="`/tournaments/${id}`" class="text-sm font-medium text-zinc-600 hover:text-black hover:underline"><i class="bi bi-arrow-left mr-1" aria-hidden="true"></i>Back to tournament</RouterLink>
    </header>

    <div v-if="loading" class="py-10 text-center text-sm text-zinc-500">Loading…</div>
    <div v-else>
      <AppAlert v-if="error" class="mb-3" type="error" :message="error" dismissible @close="error = ''" />

      <section class="mb-6" aria-labelledby="registered-heading">
        <div class="mb-3 flex items-center justify-between">
          <div>
            <h2 id="registered-heading" class="text-lg font-semibold text-black">Registered attendees</h2>
            <p class="text-sm text-zinc-500">{{ participants.length }} currently in this tournament</p>
          </div>
          <Tag :value="`${participants.length} registered`" severity="secondary" />
        </div>
        <div class="overflow-hidden rounded-lg border border-zinc-200 bg-white">
          <div v-if="participants.length===0" class="px-4 py-10 text-center text-sm text-zinc-500">No attendees yet.</div>
          <div v-for="p in participants" v-else :key="p.id" class="flex items-center justify-between gap-3 border-b border-zinc-100 px-4 py-3 last:border-0">
            <div class="flex min-w-0 items-center gap-3">
              <span :class="['inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full', p.user_id ? 'bg-zinc-900 text-white' : 'bg-zinc-100 text-zinc-600']"><i :class="p.user_id ? 'bi bi-person-fill' : 'bi bi-person'" aria-hidden="true"></i></span>
              <div class="min-w-0">
                <p class="truncate text-sm font-semibold text-black">{{ p.name }}</p>
                <p class="text-xs text-zinc-500">{{ p.user_id ? 'Registered user' : 'Virtual attendee' }}</p>
              </div>
            </div>
            <Button icon="bi bi-x-lg" text rounded severity="danger" aria-label="Remove attendee" @click="remove(p.id)" />
          </div>
        </div>
      </section>

      <section aria-labelledby="add-attendees-heading">
        <div class="mb-3">
          <h2 id="add-attendees-heading" class="text-lg font-semibold text-black">Add attendees</h2>
          <p class="text-sm text-zinc-500">Search an account or add a guest participant.</p>
        </div>
        <div class="rounded-lg border border-zinc-200 bg-white p-4">
        <div class="mb-3 flex gap-2">
          <InputText v-model="q" placeholder="Search users..." class="min-w-0 flex-1" @keydown.enter="load" />
          <Button label="Search" severity="contrast" @click="load" />
        </div>
        <div class="mb-4 border-y border-zinc-100">
          <div v-for="u in available" :key="u.id" class="flex items-center justify-between gap-3 py-2.5">
            <div class="min-w-0">
              <p class="truncate text-sm font-medium text-black">{{ u.username }}</p>
              <p class="truncate text-xs text-zinc-500">{{ u.email || 'No email address' }}</p>
            </div>
            <Button icon="bi bi-person-plus" label="Add" size="small" severity="secondary" outlined @click="addUser(u.id)" />
          </div>
          <p v-if="available.length===0" class="py-4 text-sm text-zinc-500">No available users found. Try a different search.</p>
        </div>
        <div class="flex flex-col gap-2 border-t border-zinc-100 pt-4 sm:flex-row">
          <InputText v-model="newName" placeholder="Virtual attendee name" class="min-w-0 flex-1" @keydown.enter="addVirtual" />
          <Button icon="bi bi-person-add" label="Add guest" severity="contrast" @click="addVirtual" />
        </div>
        </div>
      </section>
    </div>
  </div>
</template>
