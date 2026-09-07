<script setup lang="ts">
import { useI18n } from '@/i18n'
defineProps<{ stages: { id: string; name: string; mode: string }[] }>()
const { t } = useI18n()
function modeLabel(mode: string) {
  return t(`tournamentStructure.${['knockout', 'division', 'groups'].includes(mode) ? mode : 'custom'}`)
}
</script>

<template>
  <section class="tournament-structure" :aria-label="t('tournamentStructure.title')">
    <header>
      <i class="bi bi-layers" aria-hidden="true"></i>
      <div><h2>{{ t('tournamentStructure.title') }}</h2><p>{{ t('tournamentStructure.subtitle') }}</p></div>
      <span class="tournament-structure__total">{{ t('tournamentStructure.stages', { count: stages.length }) }}</span>
    </header>
    <ol class="tournament-structure__stages">
      <li v-for="(stage, index) in stages" :key="stage.id">
        <span class="tournament-structure__number">{{ index + 1 }}</span>
        <div><h3>{{ stage.name }}</h3><p>{{ modeLabel(stage.mode) }}</p></div>
        <i :class="stage.mode === 'knockout' ? 'bi bi-trophy' : 'bi bi-grid'" aria-hidden="true"></i>
      </li>
    </ol>
    <p v-if="!stages.length">{{ t('tournamentStructure.empty') }}</p>
  </section>
</template>

<style scoped>
.tournament-structure { border: 1px solid #293a58; border-radius: 14px; background: #111a2f; padding: 22px; }
.tournament-structure header { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; }
.tournament-structure header > i { color: #80c9ff; font-size: 22px; }
.tournament-structure h2 { margin: 0; color: #eaf1ff; font-size: 16px; font-weight: 650; }
.tournament-structure p { margin: 5px 0 0; color: #a6b8d2; font-size: 12px; line-height: 1.5; }
.tournament-structure__total { margin-inline-start: auto; border-radius: 8px; padding: 5px 9px; background: #1c2c48; color: #a4d3ff; font-size: 11px; }
.tournament-structure__stages { display: grid; gap: 12px; margin: 0; padding: 0; list-style: none; }
.tournament-structure__stages li { display: flex; align-items: center; gap: 14px; padding: 16px; border: 1px solid #293a58; border-radius: 10px; background: #162139; }
.tournament-structure__number { display: grid; flex: 0 0 30px; height: 30px; place-items: center; border-radius: 50%; background: #223b5f; color: #a8d6ff; font-size: 13px; }
.tournament-structure h3 { margin: 0; color: #eaf1ff; font-size: 14px; font-weight: 600; }
.tournament-structure__stages li > i { margin-inline-start: auto; color: #e3c476; }
</style>
