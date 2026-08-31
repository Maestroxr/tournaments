<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()

function isDashboardActive(): boolean {
  return route.name === 'dashboard' || route.path === '/' || route.path === '/dashboard'
}
function isTournamentsActive(): boolean {
  return (
    String(route.name ?? '').startsWith('tournaments') ||
    String(route.name ?? '') === 'index' ||
    route.path.startsWith('/tournaments') ||
    route.path.startsWith('/t/')
  )
}
function isUsersActive(): boolean {
  return (
    String(route.name ?? '').startsWith('users') ||
    String(route.name ?? '').startsWith('user-') ||
    route.path.startsWith('/users')
  )
}

const baseBtn =
  'inline-flex items-center gap-1.5 rounded border px-3 py-1 text-sm font-normal transition-colors whitespace-nowrap no-underline'
</script>

<template>
  <!-- Mirrors tournaments/frontend/templates/frontend/base.html:62-68 — Tailwind only, uses @theme colors -->
  <nav class="mb-2 flex flex-wrap gap-2" aria-label="Secondary">
    <RouterLink
      to="/dashboard"
      :class="[
        baseBtn,
        isDashboardActive()
          ? 'bg-dark text-white border-dark hover:bg-dark-hover'
          : 'bg-white text-dark border-dark hover:bg-dark hover:text-white',
      ]"
    >
      Dashboard
    </RouterLink>
    <RouterLink
      to="/tournaments"
      :class="[
        baseBtn,
        isTournamentsActive()
          ? 'bg-dark text-white border-dark hover:bg-dark-hover'
          : 'bg-white text-dark border-dark hover:bg-dark hover:text-white',
      ]"
    >
      Tournaments
    </RouterLink>
    <RouterLink
      to="/users"
      :class="[
        baseBtn,
        isUsersActive()
          ? 'bg-dark text-white border-dark hover:bg-dark-hover'
          : 'bg-white text-dark border-dark hover:bg-dark hover:text-white',
      ]"
    >
      Users
    </RouterLink>

    <template v-if="auth.isLoggedIn">
      <RouterLink
        to="/tournaments/new"
        :class="[baseBtn, 'bg-white text-success border-success hover:bg-success hover:text-white']"
      >
        <i class="bi bi-plus-lg" aria-hidden="true"></i> Create Tournament
      </RouterLink>
      <RouterLink
        to="/users/new"
        :class="[baseBtn, 'bg-white text-primary border-primary hover:bg-primary hover:text-white']"
      >
        <i class="bi bi-person-plus" aria-hidden="true"></i> Create User
      </RouterLink>
    </template>
  </nav>
</template>
