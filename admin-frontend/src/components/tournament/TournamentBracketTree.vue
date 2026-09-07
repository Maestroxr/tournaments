<script setup lang="ts">
import TournamentBracketMatch from './TournamentBracketMatch.vue'
import { BRACKET_CARD_WIDTH, type buildBracket } from '@/utils/tournamentBracket'
import { useI18n } from '@/i18n'
defineProps<{ layout: NonNullable<ReturnType<typeof buildBracket>> }>()
const emit = defineEmits<{ select: [id: number] }>()
const { t, direction } = useI18n()
</script>

<template>
  <div class="bracket-scroll" dir="ltr" tabindex="0" role="region" :aria-label="t('tournamentBracket.title')">
    <div class="bracket-tree" :style="{ width: `${layout.width}px`, height: `${layout.height}px` }">
      <div v-for="(column, index) in layout.columns" :key="index" class="bracket-tree__heading" :dir="direction"
        :style="{ left: `${column.x}px`, width: `${BRACKET_CARD_WIDTH}px` }">
        <i v-if="index === layout.columns.length - 1" class="bi bi-trophy" aria-hidden="true"></i>
        {{ column.name || t('tournamentWorkspace.round', { count: index + 1 }) }}
      </div>
      <svg :width="layout.width" :height="layout.height" class="bracket-tree__lines" aria-hidden="true">
        <path v-for="edge in layout.edges" :key="edge.from" :d="edge.path" :data-from="edge.from" :data-to="edge.to" />
      </svg>
      <TournamentBracketMatch v-for="node in layout.nodes" :key="node.fixture.id" :fixture="node.fixture" :sources="layout.sources.get(node.fixture.id)"
        @select="emit('select', $event)"
        class="bracket-tree__match" :style="{ left: `${node.x}px`, top: `${node.y}px`, width: `${BRACKET_CARD_WIDTH}px` }" />
    </div>
  </div>
</template>

<style scoped>
.bracket-scroll { overflow: auto; max-height: 75vh; padding: 12px 12px 16px; border: 1px solid #22324b; border-radius: 8px; background-color: #0e182a; background-image: radial-gradient(#49638335 .7px, transparent .7px); background-size: 8px 8px; scrollbar-color: #3c587f #101a2e; }
.bracket-scroll:focus-visible { outline: 2px solid #7bd4ff; outline-offset: 3px; border-radius: 8px; }
.bracket-tree { position: relative; }
.bracket-tree__heading { position: absolute; top: 0; display: flex; gap: 8px; align-items: center; color: #b7cae7; font-size: 13px; font-weight: 600; }
.bracket-tree__heading i { color: #eecb76; }
.bracket-tree__lines { position: absolute; inset: 0; pointer-events: none; }
.bracket-tree__lines path { fill: none; stroke: #90a4c0; stroke-width: 1.5; stroke-linejoin: round; }
.bracket-tree__match { position: absolute; }
</style>
