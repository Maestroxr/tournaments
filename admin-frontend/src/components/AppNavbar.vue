<script setup lang="ts">
import { RouterLink, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
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
              <span class="inline-block rounded bg-dark px-1.5 py-0.5 text-xs font-bold text-white">admin</span>
            </p>
          </h1>
          <button
            class="inline-flex items-center gap-1.5 rounded border border-dark bg-white px-3 py-1 text-sm font-normal text-dark transition-colors hover:bg-dark hover:text-white"
            @click="handleLogout"
          >
            Logout
          </button>
        </template>
        <template v-else>
          <RouterLink
            to="/login"
            class="inline-flex items-center gap-1.5 rounded border border-[#f8f9fa] bg-[#f8f9fa] px-3 py-1 text-sm font-normal text-[#212529] transition-colors hover:bg-[#e2e6ea] no-underline"
          >
            <i class="bi bi-door-open" aria-hidden="true"></i> Login
          </RouterLink>
        </template>
      </div>
    </div>
  </header>
</template>
