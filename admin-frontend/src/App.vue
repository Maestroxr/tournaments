<script setup lang="ts">
import { RouterView, useRoute } from 'vue-router'
import { computed, onMounted } from 'vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppBreadcrumb, { type BreadcrumbItem } from '@/components/AppBreadcrumb.vue'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'


const route = useRoute()
const auth = useAuthStore()
const { direction, t } = useI18n()

onMounted(() => {
  // Fetch real username from API (GET /api/auth/me) — replaces legacy localStorage fallback
  if (typeof localStorage !== 'undefined') localStorage.removeItem('token')
  auth.fetchMe()
})

// Now purely router-driven — mirrors tournaments/frontend/views.py breadcrumb context
const breadcrumbItems = computed<BreadcrumbItem[] | null>(() => {
  const meta = route.meta as { breadcrumb?: BreadcrumbItem[] | ((r: typeof route) => BreadcrumbItem[]) }
  if (!meta.breadcrumb) return null
  const items = typeof meta.breadcrumb === 'function' ? meta.breadcrumb(route) : meta.breadcrumb
  return items.map(item => item.label === 'Dashboard' ? { ...item, label: t('nav.dashboard') } : item)
})
</script>

<template>
  <div class="admin-shell flex min-h-screen flex-col" :dir="direction">
    <div v-if="breadcrumbItems" class="admin-breadcrumb">
      <AppBreadcrumb :items="breadcrumbItems" :aria-label="t('common.breadcrumb')" />
    </div>
    <AppNavbar />
    <main class="admin-main flex-1 w-full">
      <RouterView />
    </main>
  </div>
</template>
