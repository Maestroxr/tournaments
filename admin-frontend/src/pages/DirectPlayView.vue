<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import Button from 'primevue/button'
import Card from 'primevue/card'
import Dialog from 'primevue/dialog'
import InputNumber from 'primevue/inputnumber'
import ToggleSwitch from 'primevue/toggleswitch'
import SelectButton from 'primevue/selectbutton'
import Chip from 'primevue/chip'
import Tag from 'primevue/tag'
import InputGroup from 'primevue/inputgroup'
import InputGroupAddon from 'primevue/inputgroupaddon'
import coinIcon from '@/assets/6b-coin.png'
import AppAlert from '@/components/AppAlert.vue'
import DirectPlayMonitor from '@/components/DirectPlayMonitor.vue'
import GamesSidebar from '@/components/GamesSidebar.vue'
import GameFormatsEditor from '@/components/GameFormatsEditor.vue'
import type { FormatProfiles } from '@/types/directPlay'
import { apiFetch, formatApiError } from '@/services/api'
import { useI18n } from '@/i18n'
import type {
  DirectPlaySettings,
  DirectPlayTable,
  DirectPlayTablesResponse,
  GameRules,
} from '@/types/directPlay'

interface DirectPlaySettingsForm {
  format_profiles?: FormatProfiles
  game_rules: GameRules
  stake_amounts: number[]
  enabled: boolean
  friend_game_fee: number
  head_to_head_fee_percent: number
  tournament_fee_percent: number
  coin_grant_enabled: boolean
  coin_grant_amount: number
  coin_grant_interval_hours: number
}

const { t, locale } = useI18n()
const gameModes = ['match', 'friend', 'quick'] as const
const gameClocks = ['none', 'normal', 'fast', 'slow'] as const
const clockOptions = computed(() =>
  gameClocks.map((value) => ({ value, label: t('directPlay.ruleClocks.' + value) })),
)
const doublingOptions = computed(() =>
  [true, false].map((value) => ({
    value,
    label: t(value ? 'directPlay.ruleWithDoubling' : 'directPlay.ruleWithoutDoubling'),
  })),
)
const gamePoints = Array.from({ length: 25 }, (_, index) => index + 1)
const settings = ref<DirectPlaySettingsForm | null>(null)
const activeSection = ref<'monitor' | 'formats' | 'match' | 'friend' | 'quick' | 'settings'>('monitor')
const newStake = ref<number | null>(null)
const canAddStake = computed(
  () =>
    newStake.value !== null &&
    Number.isInteger(newStake.value) &&
    newStake.value >= 100 &&
    newStake.value <= 99999999 &&
    !!settings.value &&
    settings.value.stake_amounts.length < 100 &&
    !settings.value.stake_amounts.includes(newStake.value),
)
function addStake() {
  if (!canAddStake.value || !settings.value || newStake.value === null) return
  settings.value.stake_amounts = [...settings.value.stake_amounts, newStake.value].sort(
    (a, b) => a - b,
  )
  newStake.value = null
}
const tables = ref<DirectPlayTable[]>([])
const loading = ref(true)
const refreshing = ref(false)
const monitorError = ref('')
const updatedAt = ref<string | null>(null)
const historyTotal = ref(0)
let tablesRevision = 0
let refreshTimer: ReturnType<typeof setInterval> | undefined
function setTables(response: DirectPlayTablesResponse) {
  tables.value = response.tables
  historyTotal.value =
    response.history_total ??
    response.tables.filter((table) => ['completed', 'cancelled'].includes(table.status)).length
  updatedAt.value = new Date().toISOString()
}
async function refreshTables() {
  if (refreshing.value || loading.value || cancellingId.value !== null) return
  refreshing.value = true
  const revision = tablesRevision
  try {
    const response = await apiFetch<DirectPlayTablesResponse>('/api/admin/direct-play/tables')
    if (revision !== tablesRevision) return
    setTables(response)
    monitorError.value = ''
  } catch (error) {
    monitorError.value = formatApiError(error)
  } finally {
    refreshing.value = false
  }
}
const saving = ref(false)
const cancellingId = ref<number | null>(null)
const pendingCancellation = ref<DirectPlayTable | null>(null)
const loadError = ref('')
const saveError = ref('')
const cancellationError = ref('')
const success = ref('')
const rulesValid = computed(
  () =>
    !!settings.value &&
    gameModes.every((mode) => {
      const rules = settings.value!.game_rules[mode]
      return (
        rules.target_points.length > 0 &&
        rules.time_controls.length > 0 &&
        rules.doubling_options.length > 0
      )
    }),
)

const settingsValid = computed(() => {
  if (!settings.value) return false
  return (
    rulesValid.value &&
    settings.value.friend_game_fee > 0 &&
    settings.value.head_to_head_fee_percent >= 0 &&
    settings.value.head_to_head_fee_percent <= 100 &&
    settings.value.tournament_fee_percent >= 8 &&
    settings.value.tournament_fee_percent <= 10 &&
    settings.value.coin_grant_amount > 0 &&
    settings.value.coin_grant_interval_hours > 0
  )
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [nextSettings, tableResponse] = await Promise.all([
      apiFetch<DirectPlaySettings>('/api/admin/direct-play/settings'),
      apiFetch<DirectPlayTablesResponse>('/api/admin/direct-play/tables'),
    ])
    settings.value = normalizeSettings(nextSettings)
    setTables(tableResponse)
  } catch (caught: unknown) {
    loadError.value = formatApiError(caught)
  } finally {
    loading.value = false
  }
}

function normalizeSettings(value: DirectPlaySettings): DirectPlaySettingsForm {
  return {
    format_profiles: value.format_profiles ? JSON.parse(JSON.stringify(value.format_profiles)) : undefined,
    enabled: value.enabled,
    game_rules: JSON.parse(JSON.stringify(value.game_rules)),
    stake_amounts: [...(value.stake_amounts ?? [])],
    friend_game_fee: Number(value.friend_game_fee),
    head_to_head_fee_percent: Number(value.head_to_head_fee_percent),
    tournament_fee_percent: Number(value.tournament_fee_percent),
    coin_grant_enabled: value.coin_grant_enabled,
    coin_grant_amount: Number(value.coin_grant_amount),
    coin_grant_interval_hours: Number(value.coin_grant_interval_hours),
  }
}

async function saveSettings() {
  if (!settings.value || !settingsValid.value || saving.value) return
  saving.value = true
  saveError.value = ''
  success.value = ''
  try {
    const saved = await apiFetch<DirectPlaySettings>('/api/admin/direct-play/settings', {
      method: 'PUT',
      body: JSON.stringify({
        format_profiles: settings.value.format_profiles,
        enabled: settings.value.enabled,
        game_rules: settings.value.game_rules,
        stake_amounts: settings.value.stake_amounts,
        friend_game_fee: settings.value.friend_game_fee,
        head_to_head_fee_percent: settings.value.head_to_head_fee_percent,
        tournament_fee_percent: settings.value.tournament_fee_percent,
        coin_grant_enabled: settings.value.coin_grant_enabled,
        coin_grant_amount: settings.value.coin_grant_amount,
        coin_grant_interval_hours: settings.value.coin_grant_interval_hours,
      }),
    })
    settings.value = normalizeSettings(saved)
    success.value = t('directPlay.settingsSaved')
  } catch (caught: unknown) {
    saveError.value = formatApiError(caught)
  } finally {
    saving.value = false
  }
}

function requestCancellation(table: DirectPlayTable) {
  cancellationError.value = ''
  pendingCancellation.value = table
}

async function confirmCancellation() {
  const table = pendingCancellation.value
  if (!table || cancellingId.value !== null) return
  cancellingId.value = table.id
  cancellationError.value = ''
  try {
    const updated = await apiFetch<DirectPlayTable>(
      `/api/admin/direct-play/tables/${table.id}/cancel`,
      {
        method: 'POST',
      },
    )
    const index = tables.value.findIndex((item) => item.id === table.id)
    tablesRevision++
    if (index >= 0) tables.value[index] = updated
    pendingCancellation.value = null
    success.value = t('directPlay.tableCancelled')
  } catch (caught: unknown) {
    cancellationError.value = formatApiError(caught)
  } finally {
    cancellingId.value = null
  }
}

onMounted(() => {
  void load()
  refreshTimer = setInterval(() => {
    if (document.visibilityState === 'visible') void refreshTables()
  }, 15000)
})
onUnmounted(() => clearInterval(refreshTimer))
</script>

<template>
  <section class="direct-play" aria-labelledby="direct-play-heading">
    <header class="admin-page-header mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 id="direct-play-heading">{{ t('directPlay.title') }}</h1>
        <p class="mt-1 text-sm">{{ t('directPlay.subtitle') }}</p>
      </div>
      <Button
        :label="t('common.refresh')"
        icon="bi bi-arrow-clockwise"
        severity="secondary"
        outlined
        :loading="loading"
        @click="load"
      />
    </header>

    <div class="games-workspace">
      <GamesSidebar v-model="activeSection" />
      <div class="min-w-0">
        <AppAlert v-if="loadError" class="mb-4" type="error" :message="loadError" />
        <AppAlert
          v-if="success"
          class="mb-4"
          type="success"
          :message="success"
          dismissible
          @close="success = ''"
        />

        <div
          v-if="loading && !settings"
          class="grid gap-4 lg:grid-cols-2"
          :aria-label="t('directPlay.loading')"
        >
          <div v-for="index in 2" :key="index" class="h-64 animate-pulse rounded-lg bg-white"></div>
        </div>

        <template v-else-if="settings">
          <div id="games-monitor" v-show="activeSection === 'monitor'">
            <AppAlert v-if="monitorError" class="mb-4" type="error" :message="monitorError" />
            <DirectPlayMonitor
              :tables="tables"
              :refreshing="refreshing"
              :updated-at="updatedAt"
              :history-total="historyTotal"
              @refresh="refreshTables"
              @cancel="requestCancellation"
            />
          </div>
          <Card
            :id="`games-${activeSection === 'monitor' ? 'settings' : activeSection}`"
            v-show="activeSection !== 'monitor'"
            class="direct-play-settings"
          >
            <template #title>{{ activeSection === 'formats' ? (locale === 'he' ? 'פורמטים וחוקים' : 'Formats and rules') :
              t(
                activeSection === 'settings' || activeSection === 'monitor'
                  ? 'directPlay.sharedSettingsTitle'
                  : 'directPlay.modes.' + activeSection,
              )
            }}</template>
            <template #subtitle>{{ t('directPlay.settingsSubtitle') }}</template>
            <template #content>
              <form @submit.prevent="saveSettings">
                <GameFormatsEditor v-if="activeSection === 'formats' && settings.format_profiles" v-model="settings.format_profiles" />
                <div v-show="activeSection !== 'settings' && activeSection !== 'formats'">
                  <p>{{ locale === 'he' ? 'הגדרות תאימות לממשק הישן. משחקים מהמסך החדש מנוהלים באזור פורמטים וחוקים.' : 'Compatibility settings for older clients. Games created by the new interface use Formats and rules.' }}</p>
                  <h2 class="direct-play-group-title">{{ t('directPlay.gameModesTitle') }}</h2>
                  <div class="mode-fee-settings">
                    <section
                      v-show="activeSection === 'friend'"
                      class="direct-play-feature"
                      aria-labelledby="friend-settings-heading"
                    >
                      <h3 id="friend-settings-heading">{{ t('directPlay.modes.friend') }}</h3>
                      <label class="direct-play-field">
                        <span>{{ t('directPlay.friendGameFee') }}</span>
                        <InputNumber
                          v-model="settings.friend_game_fee"
                          :min="1"
                          :max-fraction-digits="0"
                          show-buttons
                          fluid
                          :aria-label="t('directPlay.friendGameFee')"
                        />
                        <small>{{ t('directPlay.friendGameFeeHint') }}</small>
                      </label>
                    </section>
                    <section
                      v-show="activeSection === 'match'"
                      class="direct-play-feature"
                      aria-labelledby="match-settings-heading"
                    >
                      <h3 id="match-settings-heading">{{ t('directPlay.modes.match') }}</h3>
                      <label class="direct-play-field">
                        <span>{{ t('directPlay.matchFee') }}</span>
                        <InputNumber
                          v-model="settings.head_to_head_fee_percent"
                          :min="0"
                          :max="100"
                          suffix="%"
                          fluid
                          :aria-label="t('directPlay.matchFee')"
                        />
                        <small>{{ t('directPlay.matchFeeHint') }}</small>
                      </label>
                    </section>
                    <section
                      v-show="activeSection === 'quick'"
                      class="direct-play-feature"
                      aria-labelledby="quick-settings-heading"
                    >
                      <h3 id="quick-settings-heading">{{ t('directPlay.modes.quick') }}</h3>
                      <div class="direct-play-field">
                        <span>{{ t('directPlay.quickFee') }}</span>
                        <output class="direct-play-fee" dir="ltr"
                          >{{ settings.head_to_head_fee_percent }}%</output
                        >
                        <small>{{ t('directPlay.quickFeeHint') }}</small>
                      </div>
                    </section>
                  </div>

                  <header class="settings-section-heading">
                    <span class="settings-section-icon"
                      ><i class="bi bi-sliders" aria-hidden="true"
                    /></span>
                    <div>
                      <h2>{{ t('directPlay.rulesTitle') }}</h2>
                      <p>{{ t('directPlay.rulesHint') }}</p>
                    </div>
                  </header>
                  <div class="game-rules-grid">
                    <section
                      v-for="gameMode in gameModes"
                      v-show="activeSection === gameMode"
                      :key="gameMode"
                      class="game-rule-card"
                      :class="{ 'is-paused': !settings.game_rules[gameMode].enabled }"
                      :data-game-mode="gameMode"
                      :aria-label="t('directPlay.modes.' + gameMode)"
                    >
                      <header class="game-rule-header">
                        <span class="game-mode-icon"
                          ><i
                            :class="
                              gameMode === 'quick'
                                ? 'bi bi-lightning-charge'
                                : gameMode === 'friend'
                                  ? 'bi bi-people'
                                  : 'bi bi-dice-5'
                            "
                            aria-hidden="true"
                        /></span>
                        <div class="game-rule-title">
                          <h3>{{ t('directPlay.modes.' + gameMode) }}</h3>
                          <Tag
                            :value="
                              t(
                                settings.game_rules[gameMode].enabled
                                  ? 'directPlay.modeActive'
                                  : 'directPlay.modePaused',
                              )
                            "
                            :severity="
                              settings.game_rules[gameMode].enabled ? 'success' : 'secondary'
                            "
                          />
                        </div>
                        <ToggleSwitch
                          v-model="settings.game_rules[gameMode].enabled"
                          :aria-label="
                            t('directPlay.modeEnabled') + ': ' + t('directPlay.modes.' + gameMode)
                          "
                        />
                      </header>
                      <div class="game-rule-body">
                        <fieldset class="rule-field">
                          <legend :id="`points-${gameMode}`">
                            {{ t('directPlay.allowedPoints') }}
                          </legend>
                          <SelectButton
                            v-model="settings.game_rules[gameMode].target_points"
                            :options="(gameMode === 'friend' ? [1, 3, 5, 7, 9] : gamePoints).map(value => ({ value, label: String(value) }))" option-label="label" option-value="value"
                            multiple
                            :allow-empty="true"
                            :aria-labelledby="`points-${gameMode}`"
                            class="point-options"
                          />
                        </fieldset>
                        <fieldset class="rule-field">
                          <legend :id="`clocks-${gameMode}`">
                            {{ t('directPlay.allowedClocks') }}
                          </legend>
                          <SelectButton
                            v-model="settings.game_rules[gameMode].time_controls"
                            :options="clockOptions"
                            option-label="label"
                            option-value="value"
                            multiple
                            :allow-empty="true"
                            :aria-labelledby="`clocks-${gameMode}`"
                            class="rule-options clock-options"
                          />
                        </fieldset>
                        <fieldset class="rule-field">
                          <legend :id="`doubling-${gameMode}`">
                            {{ t('directPlay.allowedDoubling') }}
                          </legend>
                          <SelectButton
                            v-model="settings.game_rules[gameMode].doubling_options"
                            :options="doublingOptions"
                            option-label="label"
                            option-value="value"
                            multiple
                            :allow-empty="true"
                            :aria-labelledby="`doubling-${gameMode}`"
                            class="rule-options"
                          />
                        </fieldset>
                      </div>
                    </section>
                  </div>
                </div>
                <div v-show="activeSection === 'settings'">
                  <section class="stake-settings" aria-labelledby="stake-amounts-heading">
                    <header class="settings-section-heading">
                      <img :src="coinIcon" alt="6B" class="stake-heading-coin" />
                      <div>
                        <h3 id="stake-amounts-heading">{{ t('directPlay.stakeAmounts') }}</h3>
                        <p>{{ t('directPlay.stakeAmountsHint') }}</p>
                      </div>
                    </header>
                    <div class="stake-chips">
                      <Chip
                        v-for="amount in settings.stake_amounts"
                        :key="amount"
                        class="stake-chip"
                      >
                        <span class="stake-chip-value" dir="ltr"
                          ><img :src="coinIcon" alt="6B" /><strong>{{
                            amount.toLocaleString()
                          }}</strong></span
                        >
                        <Button
                          type="button"
                          icon="bi bi-x"
                          text
                          rounded
                          severity="secondary"
                          class="stake-remove"
                          :aria-label="t('directPlay.removeStake') + ' ' + amount"
                          @click="
                            settings.stake_amounts = settings.stake_amounts.filter(
                              (value) => value !== amount,
                            )
                          "
                        />
                      </Chip>
                    </div>
                    <div class="stake-add-row">
                      <label for="new-stake">{{ t('directPlay.newStake') }}</label>
                      <div class="stake-add-controls">
                        <InputGroup class="stake-input-group"
                          ><InputGroupAddon
                            ><img :src="coinIcon" alt="6B" class="input-coin"
                          /></InputGroupAddon>
                          <InputNumber
                            input-id="new-stake"
                            v-model="newStake"
                            :min="100"
                            :max="99999999"
                            :max-fraction-digits="0"
                            :placeholder="t('directPlay.stakePlaceholder')"
                            :aria-label="t('directPlay.newStake')"
                            @keydown.enter.prevent="addStake"
                          />
                        </InputGroup>
                        <Button
                          type="button"
                          icon="bi bi-plus-lg"
                          :label="t('directPlay.addStake')"
                          :disabled="!canAddStake"
                          @click="addStake"
                        />
                      </div>
                    </div>
                  </section>
                  <div
                    class="mb-4 flex items-center justify-between gap-4 rounded-lg border border-zinc-200 bg-zinc-50 p-4"
                  >
                    <div>
                      <strong class="block text-sm text-black">{{
                        t('directPlay.enabled')
                      }}</strong>
                      <small class="text-zinc-500">{{ t('directPlay.enabledHint') }}</small>
                    </div>
                    <ToggleSwitch
                      v-model="settings.enabled"
                      :aria-label="t('directPlay.enabled')"
                    />
                  </div>
                  <div class="grid items-start gap-4 lg:grid-cols-2">
                    <section
                      class="direct-play-feature"
                      aria-labelledby="tournament-settings-heading"
                    >
                      <h3 id="tournament-settings-heading">{{ t('directPlay.tournamentFee') }}</h3>
                      <label class="direct-play-field">
                        <span>{{ t('directPlay.tournamentFee') }}</span>
                        <InputNumber
                          v-model="settings.tournament_fee_percent"
                          :min="8"
                          :max="10"
                          suffix="%"
                          fluid
                          :aria-label="t('directPlay.tournamentFee')"
                        />
                        <small>{{ t('directPlay.tournamentFeeHint') }}</small>
                      </label>
                    </section>
                    <section class="direct-play-feature" aria-labelledby="bonus-settings-heading">
                      <h3 id="bonus-settings-heading">{{ t('directPlay.coinGrantEnabled') }}</h3>
                      <div
                        class="mb-4 flex items-center justify-between gap-4 rounded-lg border border-zinc-200 bg-zinc-50 p-4"
                      >
                        <div>
                          <strong class="block text-sm text-black">{{
                            t('directPlay.coinGrantEnabled')
                          }}</strong>
                          <small class="text-zinc-500">{{
                            t('directPlay.coinGrantEnabledHint')
                          }}</small>
                        </div>
                        <ToggleSwitch
                          v-model="settings.coin_grant_enabled"
                          :aria-label="t('directPlay.coinGrantEnabled')"
                        />
                      </div>
                      <div class="grid gap-4 md:grid-cols-2">
                        <label class="direct-play-field">
                          <span>{{ t('directPlay.coinGrantAmount') }}</span>
                          <InputNumber
                            v-model="settings.coin_grant_amount"
                            :min="1"
                            :max-fraction-digits="0"
                            show-buttons
                            fluid
                            :aria-label="t('directPlay.coinGrantAmount')"
                          />
                          <small>{{ t('directPlay.coinGrantAmountHint') }}</small>
                        </label>
                        <label class="direct-play-field">
                          <span>{{ t('directPlay.coinGrantInterval') }}</span>
                          <InputNumber
                            v-model="settings.coin_grant_interval_hours"
                            :min="1"
                            suffix=" h"
                            show-buttons
                            fluid
                            :aria-label="t('directPlay.coinGrantInterval')"
                          />
                          <small>{{ t('directPlay.coinGrantIntervalHint') }}</small>
                        </label>
                      </div>
                    </section>
                  </div>
                </div>
                <AppAlert
                  v-if="!settingsValid"
                  class="mt-4"
                  type="warning"
                  :message="
                    t(rulesValid ? 'directPlay.validationError' : 'directPlay.rulesValidationError')
                  "
                />
                <AppAlert v-if="saveError" class="mt-4" type="error" :message="saveError" />
                <div class="mt-5 flex justify-end">
                  <Button
                    type="submit"
                    :label="saving ? t('common.saving') : t('directPlay.saveSettings')"
                    icon="bi bi-check2"
                    :loading="saving"
                    :disabled="!settingsValid"
                  />
                </div>
              </form>
            </template>
          </Card>
        </template>
      </div>
    </div>

    <Dialog
      :visible="Boolean(pendingCancellation)"
      modal
      :header="t('directPlay.cancelTitle')"
      :style="{ width: 'min(92vw, 30rem)' }"
      @update:visible="
        (value) => {
          if (!value && cancellingId === null) pendingCancellation = null
        }
      "
    >
      <p>
        {{
          t('directPlay.cancelWarning', {
            code: pendingCancellation?.code || pendingCancellation?.id || '',
          })
        }}
      </p>
      <p class="mt-3 text-sm text-zinc-500">{{ t('directPlay.refundHint') }}</p>
      <AppAlert v-if="cancellationError" class="mt-4" type="error" :message="cancellationError" />
      <template #footer>
        <Button
          :label="t('common.cancel')"
          severity="secondary"
          text
          :disabled="cancellingId !== null"
          @click="pendingCancellation = null"
        />
        <Button
          :label="t('directPlay.confirmCancel')"
          severity="danger"
          :loading="cancellingId !== null"
          @click="confirmCancellation"
        />
      </template>
    </Dialog>
  </section>
</template>

<style scoped>
.settings-section-heading {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin: 30px 0 18px;
}
.settings-section-heading h2,
.settings-section-heading h3 {
  margin: 0 0 6px;
  font-size: 18px;
  font-weight: 750;
  color: #edf3ff;
}
.settings-section-heading p {
  margin: 0;
  max-width: 85ch;
  font-size: 13px;
  line-height: 1.7;
  color: #94a7c5;
}
.settings-section-icon,
.game-mode-icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border: 1px solid #30496d;
  border-radius: 12px;
  background: #192c49;
  color: #91b6ff;
  font-size: 19px;
}
.game-rules-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 18px;
}
.game-rule-card {
  min-width: 0;
  border: 1px solid #2b3c59;
  border-radius: 16px;
  overflow: hidden;
  background: linear-gradient(155deg, #15223a, #101a2e);
}
.game-rule-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px;
  border-bottom: 1px solid #263653;
  background: #152139;
}
.game-rule-title {
  flex: 1;
  min-width: 0;
}
.game-rule-title h3 {
  margin: 0 0 8px;
  font-size: 16px;
  font-weight: 750;
}
.game-rule-title :deep(.p-tag) {
  font-size: 10px;
  padding: 2px 8px;
}
.game-rule-body {
  display: grid;
  grid-template-columns: 1.2fr 1fr 1fr;
  gap: 24px;
  padding: 20px;
}
.rule-field {
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}
.rule-field legend {
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 650;
  color: #adbed8;
}
.point-options {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 7px;
}
.rule-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}
.point-options :deep(.p-togglebutton),
.rule-options :deep(.p-togglebutton) {
  min-width: 0;
  min-height: 38px;
  padding: 6px;
  border: 1px solid #30415d !important;
  border-radius: 8px !important;
  background: #0d1728;
  color: #97abc8;
  box-shadow: none;
}
.point-options :deep(.p-togglebutton-checked),
.rule-options :deep(.p-togglebutton-checked) {
  border-color: #5889de !important;
  background: #224577;
  color: #eff6ff;
}
.point-options :deep(.p-togglebutton-content),
.rule-options :deep(.p-togglebutton-content) {
  padding: 2px;
  background: transparent;
  box-shadow: none;
  font-size: 13px;
}
.point-options :deep(.p-togglebutton:focus-visible),
.rule-options :deep(.p-togglebutton:focus-visible) {
  outline: 2px solid #8bc8ff;
  outline-offset: 2px;
}
.is-paused {
  border-style: dashed;
}
.stake-settings {
  margin: 24px 0;
  padding: 24px;
  border: 1px solid #36435a;
  border-radius: 16px;
  background: #111c30;
}
.stake-settings .settings-section-heading {
  margin-top: 0;
}
.stake-heading-coin {
  width: 44px;
  height: 44px;
  object-fit: contain;
}
.stake-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.stake-chip {
  gap: 10px;
  padding: 6px 8px 6px 12px;
  border: 1px solid #3b4761;
  border-radius: 12px;
  background: #19263c;
  color: #edf3ff;
}
.stake-chip-value {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}
.stake-chip-value img,
.input-coin {
  width: 26px;
  height: 26px;
  object-fit: contain;
}
.stake-remove {
  width: 30px;
  height: 30px;
  padding: 0;
}
.stake-add-row {
  margin-top: 22px;
  padding-top: 18px;
  border-top: 1px solid #2b3a53;
}
.stake-add-row > label {
  display: block;
  margin-bottom: 9px;
  font-size: 13px;
  color: #adbed8;
  font-weight: 650;
}
.stake-add-controls {
  display: flex;
  gap: 10px;
  max-width: 460px;
}
.stake-input-group {
  flex: 1;
  min-width: 0;
}
.stake-input-group :deep(.p-inputnumber),
.stake-input-group :deep(input) {
  min-width: 0;
  width: 100%;
}
@media (max-width: 1250px) {
  .game-rules-grid {
    grid-template-columns: 1fr;
  }
  .game-rule-body {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 540px) {
  .stake-settings {
    padding: 16px;
  }
  .stake-add-controls {
    flex-direction: column;
  }
  .game-rule-header,
  .game-rule-body {
    padding: 16px;
  }
}
.games-workspace {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 24px;
}
@media (max-width: 820px) {
  .games-workspace {
    grid-template-columns: 1fr;
  }
}
.direct-play-settings {
  border-inline-start: 4px solid #3f79e4;
}
.direct-play-field {
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.direct-play-field > span {
  color: var(--p-text-color);
  font-size: 0.875rem;
  font-weight: 650;
}
.direct-play-field > small {
  color: var(--p-text-muted-color);
  font-size: 0.75rem;
  line-height: 1.4;
}
.direct-play-group-title {
  margin-bottom: 1rem;
  color: var(--p-text-color);
  font-size: 1rem;
  font-weight: 650;
}
.direct-play-feature {
  min-width: 0;
  height: 100%;
  padding: 1.25rem;
  border: 1px solid var(--p-content-border-color);
  border-radius: 0.75rem;
}
.direct-play-feature h3 {
  margin: 0 0 1.25rem;
  color: var(--p-text-color);
  font-size: 1.125rem;
  font-weight: 650;
}
.direct-play-fee {
  display: block;
  padding: 0.625rem 0;
  color: var(--p-text-color);
  font-size: 1.25rem;
  font-weight: 650;
  text-align: start;
}
</style>
