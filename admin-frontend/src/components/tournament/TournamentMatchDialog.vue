<script setup lang="ts">
import { computed, onUnmounted, onMounted, ref } from 'vue'
import Drawer from 'primevue/drawer'
import Button from 'primevue/button'
import { useI18n } from '@/i18n'
import type { TournamentFixture } from '@/types/tournamentProgress'
import TournamentMatchAdminPanel from './TournamentMatchAdminPanel.vue'
import MatchLiveStatus from './MatchLiveStatus.vue'
import MatchPanelNavigation from './MatchPanelNavigation.vue'
import type { MatchPanelSection } from '@/types/matchAdministration'

const props = defineProps<{
  fixture: TournamentFixture
  round: string
  tournamentId?: string
  liveConnected?: boolean
  updatedAt?: Date | null
  sources?: Partial<Record<1 | 2, TournamentFixture>>
}>()
const emit = defineEmits<{ close: []; saved: [] }>()
const busy = ref(false)
const section = ref<MatchPanelSection>('live')
let opener: HTMLElement | null = null
onMounted(() => {
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
})
onUnmounted(() => {
  if (opener?.isConnected) opener.focus()
})
const { t, direction } = useI18n()
const status = computed(() =>
  props.fixture.admin_resolution === 'disqualify'
    ? 'matchAdmin.disqualifiedStatus'
    : props.fixture.admin_resolution === 'advance'
      ? 'matchAdmin.advancedStatus'
      : props.fixture.is_confirmed
        ? 'tournaments.confirmed'
        : props.fixture.score1 != null || props.fixture.score2 != null
          ? 'tournaments.awaitingConfirmation'
          : props.fixture.live?.status === 'playing'
            ? 'tournaments.inProgress'
            : 'tournaments.waiting',
)
const players = computed(() =>
  ([1, 2] as const).map((slot) => {
    const player = slot === 1 ? props.fixture.player1 : props.fixture.player2
    const source = props.sources?.[slot]
    return {
      slot,
      name:
        player?.name ||
        (source
          ? t('tournamentBracket.winnerOf', { id: source.id })
          : t('tournaments.awaitingPlayer')),
      score: slot === 1 ? props.fixture.score1 : props.fixture.score2,
    }
  }),
)
const hint = computed(() => {
  if (props.fixture.is_confirmed) return 'tournaments.resultLocked'
  if (props.fixture.score1 != null || props.fixture.score2 != null)
    return 'matchDetails.confirmingHint'
  if (!props.fixture.player1 || !props.fixture.player2) return 'matchDetails.waitingPlayers'
  if (props.fixture.live?.status === 'playing') return 'matchDetails.playingHint'
  if (!props.fixture.editable) return 'matchDetails.waitingRound'
  return 'matchDetails.waitingStart'
})

function close() {
  if (!busy.value) emit('close')
}
</script>

<template>
  <Drawer
    :visible="true"
    modal
    block-scroll
    :dir="direction"
    :position="direction === 'rtl' ? 'left' : 'right'"
    :header="t('matchDetails.title', { id: fixture.id })"
    :aria-label="t('matchDetails.title', { id: fixture.id })"
    :dismissable="false"
    :show-close-icon="!busy"
    :close-on-escape="!busy"
    :close-button-props="{
      severity: 'secondary',
      text: true,
      rounded: true,
      'aria-label': t('matchDetails.close'),
    }"
    :style="{
      width: 'min(560px, 100vw)',
      maxWidth: '100vw',
      height: '100dvh',
      background: '#111b30',
      color: '#edf3ff',
      border: '1px solid #2b3e5e',
      borderRadius: '0',
      boxShadow: '0 0 60px #0005',
    }"
    :pt="{
      mask: { style: { background: 'rgba(3, 9, 19, 0.28)' } },
      header: {
        style: { borderBottom: '1px solid #2b3e5e', padding: '18px 22px', flexShrink: '0' },
      },
      content: {
        style: {
          padding: '20px',
          overflowY: 'auto',
          overscrollBehavior: 'contain',
          minHeight: '0',
        },
      },
      footer: { style: { borderTop: '1px solid #2b3e5e', padding: '12px 20px', flexShrink: '0' } },
    }"
    @update:visible="close"
  >
    <div class="match-dialog__meta">
      <span>{{ round }}</span
      ><span class="match-dialog__status">{{ t(status) }}</span>
    </div>
    <div class="match-dialog__players">
      <div v-for="player in players" :key="player.slot" class="match-dialog__player">
        <span>{{ player.name }}</span
        ><strong>{{ player.score ?? '–' }}</strong>
      </div>
    </div>
    <MatchPanelNavigation
      v-if="tournamentId"
      v-model="section"
      :disabled="busy"
      :content-id="`match-content-${fixture.id}`"
    />
    <div :id="`match-content-${fixture.id}`">
      <div v-show="section === 'live'">
        <p class="match-dialog__hint">{{ t(hint) }}</p>
        <p
          v-if="!fixture.is_confirmed && (fixture.score1 != null || fixture.score2 != null)"
          class="match-dialog__hint"
        >
          {{
            t('tournaments.confirmations', {
              count: fixture.confirmations,
              required: fixture.required_confirmations,
            })
          }}
        </p>
        <MatchLiveStatus :fixture="fixture" :connected="liveConnected" :updated-at="updatedAt" />
      </div>
      <TournamentMatchAdminPanel
        v-if="tournamentId"
        v-show="section !== 'live'"
        :key="fixture.id"
        :tournament-id="tournamentId"
        :fixture-id="fixture.id"
        :section="section"
        @busy="busy = $event"
        @saved="emit('saved')"
      />
    </div>
    <template #footer>
      <div class="match-dialog__footer">
        <span
          ><i class="bi bi-shield-lock" aria-hidden="true"></i>
          {{ t('matchDetails.adminOnly') }}</span
        >
        <Button
          :label="t('matchDetails.close')"
          severity="secondary"
          outlined
          :disabled="busy"
          @click="close"
        />
      </div>
    </template>
  </Drawer>
</template>

<style scoped>
.match-dialog__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
  font-size: 12px;
  color: #a9bdd9;
}
.match-dialog__status {
  border: 1px solid #375371;
  border-radius: 99px;
  padding: 4px 10px;
  color: #8cdbff;
}
.match-dialog__players {
  overflow: hidden;
  border: 1px solid #314563;
  border-radius: 12px;
  background: #19273e;
}
.match-dialog__player {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
}
.match-dialog__player + .match-dialog__player {
  border-top: 1px solid #314563;
}
.match-dialog__player span {
  min-width: 0;
  overflow-wrap: anywhere;
  font-weight: 600;
}
.match-dialog__player strong {
  min-width: 30px;
  font-size: 24px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.match-dialog__hint {
  margin-top: 14px;
  color: #b5c6df;
  font-size: 13px;
  line-height: 1.6;
}
.match-dialog__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.match-dialog__footer span {
  color: #9eb0ca;
  font-size: 12px;
}
</style>
