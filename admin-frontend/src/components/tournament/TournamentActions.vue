<script setup lang="ts">
import { computed } from 'vue'
import ProgressBar from 'primevue/progressbar'
import TournamentActionCard from './TournamentActionCard.vue'
import { useI18n } from '@/i18n'

const props = defineProps<{
  tournamentId: number
  state: string
  lifecycleState?: string
  participantCount: number
  minPlayers: number
  hasFormat?: boolean
  starting?: boolean
  publishing?: boolean
}>()
const emit = defineEmits<{ start: []; publish: [] }>()
const { t } = useI18n()
const remaining = computed(() => Math.max(0, props.minPlayers - props.participantCount))
const ready = computed(() => props.state === 'open' && remaining.value === 0)
const hasBracket = computed(() => ['active', 'finished'].includes(props.state))
const progress = computed(() => props.minPlayers > 0 ? Math.min(100, props.participantCount / props.minPlayers * 100) : 0)
interface PrimaryAction {
  title: string
  hint: string
  label: string
  description: string
  icon: string
  to?: string
  command?: 'start' | 'publish'
}
const primary = computed<PrimaryAction>(() => {
  const root = `/tournaments/${props.tournamentId}`
  if (props.state === 'draft' && !props.hasFormat) return {
    title: t('tournamentActions.completeSetup'),
    hint: t('tournamentActions.completeSetupHint'),
    label: t('tournamentActions.openSettings'),
    description: t('tournamentActions.openSettingsHint'),
    icon: 'bi bi-sliders',
    to: `${root}/settings`,
  }
  if (props.state === 'draft') return {
    title: t('tournamentActions.publishRegistration'),
    hint: t('tournamentActions.publishRegistrationHint'),
    label: t('tournamentActions.publish'),
    description: t('tournamentActions.publishHint'),
    icon: 'bi bi-megaphone',
    command: 'publish',
  }
  if (props.state === 'open' && remaining.value > 0) return {
    title: t('tournamentActions.addPlayers'),
    hint: t('tournamentActions.playersHint'),
    label: t('tournamentActions.managePlayers'),
    description: t('tournamentActions.manageHint'),
    icon: 'bi bi-person-plus',
    to: `${root}/players`,
  }
  if (ready.value) return {
    title: t('tournamentActions.ready'),
    hint: t('tournamentActions.readyHint'),
    label: t('tournamentActions.start'),
    description: t('tournamentActions.startHint'),
    icon: 'bi bi-play',
    command: 'start',
  }
  if (props.state === 'active') return {
    title: t('tournamentActions.runTournament'),
    hint: t('tournamentActions.runTournamentHint'),
    label: t('tournamentActions.openLive'),
    description: t('tournamentActions.openLiveHint'),
    icon: 'bi bi-broadcast',
    to: `${root}/live`,
  }
  return {
    title: t('tournamentActions.reviewResults'),
    hint: t('tournamentActions.reviewResultsHint'),
    label: t('tournamentActions.openResults'),
    description: t('tournamentActions.openResultsHint'),
    icon: 'bi bi-trophy',
    to: `${root}/results`,
  }
})
const primaryLoading = computed(() => primary.value.command === 'start' ? props.starting : primary.value.command === 'publish' ? props.publishing : false)
function runPrimary() {
  if (primary.value.command === 'start' && ready.value && !props.starting) emit('start')
  if (primary.value.command === 'publish' && props.hasFormat && !props.publishing) emit('publish')
}
</script>

<template>
  <section class="tournament-actions" :aria-label="t('tournamentActions.title')">
    <div class="tournament-actions__next">
      <span class="tournament-actions__eyebrow">{{ t('tournamentActions.nextStep') }}</span>
      <h2>{{ primary.title }}</h2>
      <p>{{ primary.hint }}</p>
      <div v-if="state === 'open'" class="tournament-actions__registration">
        <div class="tournament-actions__count"><strong>{{ participantCount }}</strong><span>{{ t('tournamentActions.minimum', { count: minPlayers }) }}</span></div>
        <ProgressBar :value="progress" :show-value="false" :aria-label="t('tournamentActions.registrationProgress')" style="height: 6px" />
        <p class="tournament-actions__footnote">{{ t(remaining ? 'tournamentActions.remaining' : 'tournamentActions.minimumReached', { count: remaining }) }}</p>
      </div>
      <TournamentActionCard
        class="tournament-actions__primary"
        :label="primary.label"
        :description="primary.description"
        :icon="primary.icon"
        :to="primary.to"
        tone="green"
        :loading="primaryLoading"
        @activate="runPrimary"
      />
    </div>
    <div class="tournament-actions__links">
      <h3>{{ t('tournamentActions.title') }}</h3>
      <TournamentActionCard
        v-if="primary.to !== `/tournaments/${tournamentId}/settings`"
        :label="t('tournamentWorkspace.settings')"
        :description="t('tournamentWorkspace.settingsHint')"
        icon="bi bi-sliders"
        :to="`/tournaments/${tournamentId}/settings`"
      />
      <TournamentActionCard
        v-if="state !== 'draft' && primary.to !== `/tournaments/${tournamentId}/players`"
        :label="t(hasBracket ? 'tournamentActions.viewPlayers' : 'tournamentActions.managePlayers')"
        :description="t(hasBracket ? 'tournamentActions.viewPlayersHint' : 'tournamentActions.manageHint')"
        icon="bi bi-people"
        :to="`/tournaments/${tournamentId}/players`"
      />
      <TournamentActionCard
        :label="t('tournamentActions.bracket')"
        :description="t(hasBracket ? 'tournamentActions.bracketHint' : 'tournamentActions.bracketLocked')"
        icon="bi bi-diagram-3"
        :to="`/tournaments/${tournamentId}/bracket`"
        :disabled="!hasBracket"
      />
      <TournamentActionCard
        v-if="hasBracket"
        :label="t('tournamentWorkspace.standings')"
        :description="t('tournamentActions.standingsHint')"
        icon="bi bi-bar-chart"
        :to="`/tournaments/${tournamentId}/standings`"
      />
    </div>
  </section>
</template>

<style scoped>
.tournament-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.tournament-actions__next { padding: 24px; border: 1px solid #294267; border-radius: 14px; background: linear-gradient(145deg, #132842, #111b30); }
.tournament-actions__eyebrow { color: #7ad4ff; font-size: 11px; font-weight: 650; letter-spacing: .06em; text-transform: uppercase; }
.tournament-actions__next h2 { margin: 12px 0 8px; color: #f1f6ff; font-size: 22px; font-weight: 650; line-height: 1.35; }
.tournament-actions__next p { color: #acbfd9; font-size: 13px; line-height: 1.6; }
.tournament-actions__registration { margin-top: 24px; }
.tournament-actions__count { display: flex; align-items: baseline; flex-wrap: wrap; gap: 10px; margin: 0 0 12px; color: #b5c8e0; font-size: 12px; }
.tournament-actions__count strong { color: #fff; font-size: 34px; line-height: 1; }
.tournament-actions__next .tournament-actions__footnote { margin-top: 10px; font-size: 12px; }
.tournament-actions__primary { margin-top: 22px; }
.tournament-actions__links { display: grid; align-content: start; gap: 10px; }
.tournament-actions__links h3 { margin: 0 0 4px; color: #e8f0ff; font-size: 14px; font-weight: 650; }
@media (max-width: 640px) { .tournament-actions { grid-template-columns: 1fr; } }
</style>
