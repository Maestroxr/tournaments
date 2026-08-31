<script setup lang="ts">
import { RouterView, useRoute } from 'vue-router'
import { computed, onMounted } from 'vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppBreadcrumb, { type BreadcrumbItem } from '@/components/AppBreadcrumb.vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const auth = useAuthStore()

onMounted(() => {
  // Fetch real username from API (GET /api/auth/me) — replaces legacy localStorage fallback
  if (typeof localStorage !== 'undefined') localStorage.removeItem('token')
  auth.fetchMe()
})

// Now purely router-driven — mirrors tournaments/frontend/views.py breadcrumb context
const breadcrumbItems = computed<BreadcrumbItem[] | null>(() => {
  const meta = route.meta as { breadcrumb?: BreadcrumbItem[] | ((r: typeof route) => BreadcrumbItem[]) }
  if (!meta.breadcrumb) return null
  return typeof meta.breadcrumb === 'function' ? meta.breadcrumb(route) : meta.breadcrumb
})
</script>

<template>
  <!-- Mirrors base.html order: breadcrumb first, then tabs -->
  <div v-if="breadcrumbItems" >
    <AppBreadcrumb :items="breadcrumbItems" />
  </div>
  <AppNavbar />
  <main class="mx-auto max-w-6xl p-6">
    <RouterView />
  </main>
</template>
