<script setup lang="ts">
import { useI18n } from '@/i18n'
defineProps<{ finished: boolean; podium: Array<{ id: number; name: string }> }>()
const { t } = useI18n()
</script>

<template>
  <section class="rounded-xl border border-zinc-200 bg-white p-6">
    <ol v-if="finished && podium.length" class="space-y-3">
      <li v-for="(player, index) in podium" :key="player.id" class="flex items-center gap-4 rounded-lg bg-zinc-50 p-4">
        <span class="text-lg font-bold text-amber-700">{{ index + 1 }}</span>
        <span class="font-semibold text-black">{{ player.name }}</span>
        <i v-if="index === 0" class="bi bi-trophy ms-auto text-amber-700" aria-hidden="true"></i>
      </li>
    </ol>
    <div v-else class="py-8 text-center">
      <i class="bi bi-trophy text-3xl text-zinc-500" aria-hidden="true"></i>
      <p class="mt-4 text-sm text-zinc-500">{{ t(finished ? 'tournamentWorkspace.noStandings' : 'tournamentWorkspace.standingsPending') }}</p>
    </div>
  </section>
</template>
