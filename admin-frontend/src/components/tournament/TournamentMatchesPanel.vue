<script setup lang="ts">
import TournamentBracketMatch from './TournamentBracketMatch.vue'
import { computed } from 'vue'
import TournamentBracketTree from './TournamentBracketTree.vue'
import { buildBracket } from '@/utils/tournamentBracket'
import type { TournamentProgressStage } from '@/types/tournamentProgress'
import { useI18n } from '@/i18n'
const props = defineProps<{ stages: Record<string, TournamentProgressStage> }>()
const emit = defineEmits<{ select: [id: number] }>()
const { t } = useI18n()
const panels = computed(() => Object.entries(props.stages).map(([id, stage]) => ({ id, stage, layout: buildBracket(stage) })))
</script>

<template>
  <div class="space-y-5">
    <section v-for="({ stage, id, layout }, index) in panels" :key="id" class="min-w-0 rounded-xl border border-zinc-200 bg-white p-5">
      <h3 class="mb-4 text-base font-semibold text-black">{{ t('tournamentWorkspace.stage', { count: index + 1 }) }}</h3>
      <template v-if="layout">
        <p class="mb-4 text-xs text-zinc-500">{{ t('tournamentBracket.hint') }}</p>
        <TournamentBracketTree :layout="layout" @select="emit('select', $event)" />
      </template>
      <div v-else>
        <p v-if="stage.bracket_kind === undefined && stage.levels.length > 1" class="mb-5 text-xs text-zinc-500" role="status">{{ t('tournamentBracket.missingConnections') }}</p>
        <div class="matches-panel__rounds">
        <section v-for="(level, index) in stage.levels" :key="index" class="min-w-0">
          <h4 class="mb-3 text-sm font-semibold text-zinc-500">{{ level.name || t('tournamentWorkspace.round', { count: index + 1 }) }}</h4>
          <div class="matches-panel__cards">
            <TournamentBracketMatch v-for="fixture in level.fixtures" :key="fixture.id" :fixture="fixture" @select="emit('select', $event)" />
            <p v-if="!level.fixtures.length" class="rounded-lg border border-dashed border-zinc-200 p-4 text-sm text-zinc-500">{{ t('tournamentWorkspace.waitingRound') }}</p>
          </div>
        </section>
        </div>
      </div>
    </section>
    <p v-if="!Object.keys(stages).length" class="text-sm text-zinc-500">{{ t('tournamentWorkspace.noMatches') }}</p>
  </div>
</template>

<style scoped>
.matches-panel__rounds { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 216px), 1fr)); gap: 32px; align-items: start; }
.matches-panel__cards { display: grid; gap: 42px; padding-top: 20px; }
</style>
