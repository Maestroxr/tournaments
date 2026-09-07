<script setup lang="ts">
import TournamentFixtureCard from '@/components/TournamentFixtureCard.vue'
import type { TournamentFixture } from '@/types/tournamentProgress'

withDefaults(defineProps<{
  title: string
  hint: string
  fixtures: TournamentFixture[]
  empty: string
  tone?: 'neutral' | 'playing' | 'warning' | 'complete'
}>(), { tone: 'neutral' })
const emit = defineEmits<{ select: [fixtureId: number] }>()
</script>

<template>
  <section :class="['live-group', `live-group--${tone}`]">
    <header>
      <div><h3>{{ title }}</h3><p>{{ hint }}</p></div>
      <span>{{ fixtures.length }}</span>
    </header>
    <div v-if="fixtures.length" class="live-group__grid">
      <TournamentFixtureCard v-for="fixture in fixtures" :key="fixture.id" :fixture="fixture" @select="emit('select', $event)" />
    </div>
    <p v-else class="live-group__empty">{{ empty }}</p>
  </section>
</template>

<style scoped>
.live-group { overflow: hidden; border: 1px solid #293a56; border-radius: 14px; background: #0f192c; }
.live-group > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; border-bottom: 1px solid #263650; background: #131f35; }
.live-group h3 { margin: 0; color: #edf4ff; font-size: 14px; font-weight: 700; }
.live-group header p { margin: 3px 0 0; color: #879ab6; font-size: 10px; }
.live-group header > span { display: grid; min-width: 27px; height: 27px; place-items: center; border-radius: 999px; background: #263954; color: #b7d8fa; font-size: 11px; font-weight: 800; }
.live-group--playing { border-color: #285a6c; }
.live-group--playing header > span { background: #1f6178; color: #bceeff; }
.live-group--warning { border-color: #66522e; }
.live-group--warning header > span { background: #56441f; color: #f6d47a; }
.live-group--complete header > span { background: #1e5749; color: #a4ead1; }
.live-group__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 14px; }
.live-group__empty { margin: 0; padding: 22px 16px; color: #7185a3; font-size: 11px; text-align: center; }
@media (max-width: 820px) { .live-group__grid { grid-template-columns: 1fr; } }
</style>
