<script setup lang="ts">
import { RouterLink, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Button from 'primevue/button'
import AppTabs from '@/components/AppTabs.vue'

const auth = useAuthStore()
const router = useRouter()

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <!-- Header wraps the dedicated AppTabs component (mirrors base.html:62-68) -->
  <header class="border-b border-zinc-200 bg-white">
    <div class="flex w-full items-center gap-3 px-6 py-3">
      <AppTabs v-if="auth.isLoggedIn" />

      <!-- Right: auth — exact replica of base.html:71-76 — Tailwind only -->
      <div class="ml-auto flex items-center gap-3">
        <template v-if="auth.isLoggedIn">
          <h1 class="m-0 text-right leading-none">
            <p class="text-muted text-sm font-normal">
              <i class="bi bi-person" aria-hidden="true"></i> {{ auth.user?.username }}
              <span class="ml-2 inline-block rounded bg-emerald-50 px-1.5 py-0.5 text-xs font-bold text-emerald-700">Balance {{ Number(auth.user?.balance || 0).toFixed(2) }}</span>
              <span class="inline-block rounded bg-dark px-1.5 py-0.5 text-xs font-bold text-white">admin</span>
            </p>
          </h1>
          <Button label="Logout" icon="bi bi-box-arrow-right" size="small" severity="contrast" outlined @click="handleLogout" />
        </template>
        <template v-else>
          <Button as="router-link" to="/login" label="Login" icon="bi bi-door-open" size="small" severity="secondary" />
        </template>
      </div>
    </div>
  </header>
</template>
