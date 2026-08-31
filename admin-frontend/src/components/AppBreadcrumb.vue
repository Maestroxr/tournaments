<script setup lang="ts">
import { RouterLink } from 'vue-router'

export interface BreadcrumbItem {
  label: string
  to?: string
}

defineProps<{
  items: BreadcrumbItem[]
}>()
</script>

<template>
  <!-- Mirrors tournaments/frontend/templates/frontend/base.html:47-57 — Tailwind only -->
  <nav aria-label="breadcrumb" >
    <ol class="flex flex-wrap items-center  bg-breadcrumb-bg px-4 py-3 text-sm">
      <li
        v-for="(item, idx) in items"
        :key="idx"
        class="inline-flex items-center"
        :class="{ 'text-muted': idx === items.length - 1 }"
        :aria-current="idx === items.length - 1 ? 'page' : undefined"
      >
        <span v-if="idx > 0" class="mx-2 text-muted" aria-hidden="true">/</span>
        <RouterLink
          v-if="item.to && idx !== items.length - 1"
          :to="item.to"
          class="text-primary no-underline hover:text-primary-hover hover:underline"
        >
          {{ item.label }}
        </RouterLink>
        <span v-else :class="idx === items.length - 1 ? 'text-muted' : 'text-primary'">
          {{ item.label }}
        </span>
      </li>
    </ol>
  </nav>
</template>
