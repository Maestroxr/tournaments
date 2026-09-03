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
  <nav class="admin-breadcrumb-nav" aria-label="Breadcrumb">
    <ol class="admin-breadcrumb-list">
      <li
        v-for="(item, idx) in items"
        :key="idx"
        class="inline-flex items-center"
        :class="{ 'admin-breadcrumb-current': idx === items.length - 1 }"
        :aria-current="idx === items.length - 1 ? 'page' : undefined"
      >
        <span v-if="idx > 0" class="admin-breadcrumb-separator" aria-hidden="true">/</span>
        <RouterLink
          v-if="item.to && idx !== items.length - 1"
          :to="item.to"
          class="admin-breadcrumb-link"
        >
          {{ item.label }}
        </RouterLink>
        <span v-else :class="idx === items.length - 1 ? 'admin-breadcrumb-current' : 'admin-breadcrumb-link'">
          {{ item.label }}
        </span>
      </li>
    </ol>
  </nav>
</template>
