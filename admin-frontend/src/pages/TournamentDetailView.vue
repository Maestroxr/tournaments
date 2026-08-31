<script setup lang="ts">
defineProps<{ id: string }>()
</script>

<template>
  <div>
    <h1 class="text-2xl font-bold">{{ id === 'test-1' ? 'test 1' : id }}</h1>
    <p class="mt-2 text-zinc-600">Tournament detail placeholder — wire to GET /api/admin/tournaments/{{ id }}</p>
  </div>
</template>
