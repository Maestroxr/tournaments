<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const auth = useAuthStore()
const route = useRoute()
const { t } = useI18n()

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
function isTransfersActive(): boolean {
  return String(route.name ?? '').startsWith('transfers') || route.path.startsWith('/transfers')
}

const baseBtn = 'admin-nav-link'
</script>

<template>
  <!-- Mirrors tournaments/frontend/templates/frontend/base.html:62-68 — Tailwind only, uses @theme colors -->
  <nav class="admin-nav" :aria-label="t('nav.primary')">
    <RouterLink
      to="/dashboard"
      :class="[
        baseBtn,
        isDashboardActive()
          ? 'bg-dark text-white border-dark hover:bg-dark-hover'
          : 'bg-white text-dark border-dark hover:bg-dark hover:text-white',
      ]"
    >
      {{ t('nav.dashboard') }}
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
      {{ t('nav.tournaments') }}
    </RouterLink>
    <RouterLink
      to="/tournaments?state=finished"
      :class="[baseBtn, route.query.state === 'finished'
        ? 'bg-dark text-white border-dark hover:bg-dark-hover'
        : 'bg-white text-dark border-dark hover:bg-dark hover:text-white']"
    >
      {{ t('nav.history') }}
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
      {{ t('nav.users') }}
    </RouterLink>
    <RouterLink
      to="/transfers"
      :class="[
        baseBtn,
        isTransfersActive()
          ? 'bg-dark text-white border-dark hover:bg-dark-hover'
          : 'bg-white text-dark border-dark hover:bg-dark hover:text-white',
      ]"
    >
      {{ t('nav.transfers') }}
    </RouterLink>

    <template v-if="auth.isLoggedIn">
      <RouterLink
        to="/tournaments/new"
        :class="[baseBtn, 'bg-white text-success border-success hover:bg-success hover:text-white']"
      >
        <i class="bi bi-plus-lg" aria-hidden="true"></i> {{ t('nav.createTournament') }}
      </RouterLink>
      <RouterLink
        to="/users/new"
        :class="[baseBtn, 'bg-white text-primary border-primary hover:bg-primary hover:text-white']"
      >
        <i class="bi bi-person-plus" aria-hidden="true"></i> {{ t('nav.createUser') }}
      </RouterLink>
    </template>
  </nav>
</template>
