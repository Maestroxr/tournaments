<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import Button from 'primevue/button'
import Card from 'primevue/card'
import Dialog from 'primevue/dialog'
import Select from 'primevue/select'
import Tag from 'primevue/tag'
import Paginator from 'primevue/paginator'
import SearchBar from '@/components/SearchBar.vue'
import UserQuickView from '@/components/UserQuickView.vue'
import { useI18n } from '@/i18n'
import type { DirectPlayTable } from '@/types/directPlay'

const props = defineProps<{
  tables: DirectPlayTable[]
  refreshing: boolean
  updatedAt: string | null
  historyTotal: number
}>()
const emit = defineEmits<{ cancel: [table: DirectPlayTable]; refresh: [] }>()
const { t, locale } = useI18n()
const scope = ref('waiting')
const mode = ref('all')
const format = ref('all')
const formats = computed(() => [
  { value: 'all', label: locale.value === 'he' ? 'כל הפורמטים' : 'All formats' },
  { value: 'match', label: locale.value === 'he' ? 'סדרה לנקודות' : 'Match play' },
  { value: 'money', label: locale.value === 'he' ? 'מטבעות לנקודה' : 'Money game' },
  { value: 'legacy', label: locale.value === 'he' ? 'משחקים מהמערכת הישנה' : 'Legacy games' },
])
function formatLabel(table: DirectPlayTable) {
  return formats.value.find(item => item.value === (table.game_format ?? 'legacy'))?.label
}
const query = ref('')
const first = ref(0)
const selectedId = ref<number | null>(null)
const selected = computed(() => props.tables.find((table) => table.id === selectedId.value))
const scopes = ['waiting', 'active', 'history']
function bucket(table: DirectPlayTable) {
  if (['completed', 'cancelled'].includes(table.status)) return 'history'
  return ['open', 'waiting'].includes(table.status) ? 'waiting' : 'active'
}
function gameMode(table: DirectPlayTable) {
  return table.is_quick_match ? 'quick' : table.mode === 'friend' ? 'friend' : 'match'
}
const modes = computed(() =>
  ['all', 'friend', 'match', 'quick'].map((value) => ({
    value,
    label: t(value === 'all' ? 'directPlay.monitor.allModes' : `directPlay.modes.${value}`),
  })),
)
const counts = computed(() =>
  Object.fromEntries(
    scopes.map((key) => [key, props.tables.filter((table) => bucket(table) === key).length]),
  ),
)
const filtered = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  return props.tables.filter(
    (table) =>
      bucket(table) === scope.value &&
      (mode.value === 'all' || gameMode(table) === mode.value) &&
      (format.value === 'all' || (table.game_format ?? 'legacy') === format.value) &&
      (!needle ||
        [table.host, table.guest, table.code, String(table.id)].some((value) =>
          value?.toLocaleLowerCase().includes(needle),
        )),
  )
})
const page = computed(() => filtered.value.slice(first.value, first.value + 12))
watch(
  () => filtered.value.length,
  (length) => {
    if (first.value >= length) first.value = Math.max(0, Math.floor((length - 1) / 12) * 12)
  },
)
function statusSeverity(status: string) {
  if (status === 'completed') return 'success'
  if (status === 'cancelled') return 'secondary'
  return ['playing', 'active'].includes(status) ? 'info' : 'warn'
}
function date(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString(locale.value === 'he' ? 'he-IL' : 'en-GB') : '—'
}
function waitingMinutes(table: DirectPlayTable) {
  return Math.max(
    0,
    Math.floor(
      (new Date(props.updatedAt ?? Date.now()).getTime() - new Date(table.created_at).getTime()) /
        60000,
    ),
  )
}
function changeFilters() {
  first.value = 0
}
</script>

<template>
  <Card class="direct-monitor">
    <template #title>{{ t('directPlay.monitor.title') }}</template>
    <template #subtitle>{{ t('directPlay.monitor.subtitle') }}</template>
    <template #content>
      <div class="monitor-toolbar">
        <span role="status">{{
          t('directPlay.monitor.updated', { time: updatedAt ? date(updatedAt) : '—' })
        }}</span>
        <Button
          :label="t('common.refresh')"
          icon="bi bi-arrow-clockwise"
          outlined
          :loading="refreshing"
          @click="emit('refresh')"
        />
      </div>
      <div class="monitor-scopes" role="group" :aria-label="t('directPlay.monitor.statusFilter')">
        <Button
          v-for="key in scopes"
          :key="key"
          :label="`${t(`directPlay.monitor.${key}`)} (${counts[key]})`"
          :aria-pressed="scope === key"
          :outlined="scope !== key"
          severity="secondary"
          @click="() => {
            scope = key
            changeFilters()
          }"
        />
      </div>
      <div class="monitor-filters">
        <Select v-model="format" :options="formats" option-label="label" option-value="value" :aria-label="locale === 'he' ? 'פורמט' : 'Format'" @update:model-value="changeFilters" />
        <SearchBar
          v-model="query"
          :placeholder="t('directPlay.monitor.search')"
          @update:model-value="changeFilters"
        />
        <Select
          v-model="mode"
          :options="modes"
          option-label="label"
          option-value="value"
          :aria-label="t('directPlay.mode')"
          @update:model-value="changeFilters"
        />
      </div>
      <p
        v-if="scope === 'history' && historyTotal > (counts.history ?? 0)"
        class="monitor-hint"
        role="status"
      >
        {{
          t('directPlay.monitor.historyLimit', { shown: counts.history ?? 0, total: historyTotal })
        }}
      </p>
      <div class="monitor-grid">
        <article
          v-for="table in page"
          :key="table.id"
          class="monitor-match"
          :data-table-id="table.id"
        >
          <header>
            <strong
              >{{ formatLabel(table) }} · {{ t(`directPlay.modes.${gameMode(table)}`) }} · <bdi>{{ table.code }}</bdi></strong
            >
            <Tag
              :value="t(`directPlay.statuses.${table.status}`)"
              :severity="statusSeverity(table.status)"
            />
          </header>
          <div class="monitor-matchup">
            <UserQuickView
              interactive
              :user-id="table.host_id ?? null"
              :username="table.host ?? '—'"
            />
            <span class="monitor-hint">{{ t('tournaments.versus') }}</span>
            <UserQuickView
              interactive
              v-if="table.guest"
              :user-id="table.guest_id ?? null"
              :username="table.guest"
            />
            <span v-else class="monitor-waiting">{{
              t('directPlay.monitor.waitingOpponent')
            }}</span>
          </div>
          <p v-if="bucket(table) === 'waiting'" class="monitor-hint">
            {{ t('directPlay.monitor.waitDuration', { minutes: waitingMinutes(table) }) }}
          </p>
          <p>
            {{ t('directPlay.points', { count: table.target_points }) }} ·
            {{ Number(table.amount).toLocaleString() }} {{ t('directPlay.amount') }} ·
            {{
              t(table.doubling_enabled ? 'directPlay.withDoubling' : 'directPlay.withoutDoubling')
            }}
          </p>
          <p v-if="table.winner">
            {{ t('tournaments.winner') }}: <bdi>{{ table.winner }}</bdi>
          </p>
          <footer>
            <Button
              :label="t('directPlay.monitor.details')"
              icon="bi bi-sliders"
              size="small"
              outlined
              @click="selectedId = table.id"
            />
            <Button
              v-if="bucket(table) !== 'history'"
              :label="t('directPlay.cancelAndRefund')"
              icon="bi bi-x-circle"
              size="small"
              severity="danger"
              text
              @click="emit('cancel', table)"
            />
          </footer>
        </article>
      </div>
      <p v-if="!filtered.length" class="monitor-empty">{{ t('directPlay.monitor.empty') }}</p>
      <Paginator
        v-if="filtered.length > 12"
        v-model:first="first"
        :rows="12"
        :total-records="filtered.length"
      />
    </template>
  </Card>

  <Dialog
    :visible="!!selected"
    modal
    :header="t('directPlay.monitor.details')"
    :style="{ width: 'min(94vw, 48rem)' }"
    @update:visible="
      (value) => {
        if (!value) selectedId = null
      }
    "
  >
    <template v-if="selected">
      <div class="monitor-matchup">
        <UserQuickView
          interactive
          :key="`host-${selected.id}`"
          :user-id="selected.host_id ?? null"
          :username="selected.host ?? '—'"
        />
        <span>{{ t('tournaments.versus') }}</span>
        <UserQuickView
          interactive
          v-if="selected.guest"
          :key="`guest-${selected.id}`"
          :user-id="selected.guest_id ?? null"
          :username="selected.guest"
        />
        <span v-else>{{ t('directPlay.monitor.waitingOpponent') }}</span>
      </div>
      <dl class="monitor-details">
        <div>
          <dt>{{ t('directPlay.code') }}</dt>
          <dd>
            <bdi>{{ selected.code }}</bdi>
          </dd>
        </div>
        <div>
          <dt>{{ t('directPlay.mode') }}</dt>
          <dd>{{ formatLabel(selected) }} · {{ t(`directPlay.modes.${gameMode(selected)}`) }}</dd>
        </div>
        <div>
          <dt>{{ t('directPlay.status') }}</dt>
          <dd>{{ t(`directPlay.statuses.${selected.status}`) }}</dd>
        </div>
        <div>
          <dt>{{ t('directPlay.amount') }}</dt>
          <dd>{{ Number(selected.amount).toLocaleString() }}</dd>
        </div>
        <div>
          <dt>{{ t('directPlay.monitor.fee') }}</dt>
          <dd>
            <bdi>{{ selected.settlement?.fee ?? (selected.game_format === 'money' ? '—' : selected.fee_per_player) }} ({{ selected.fee_percent }}%)</bdi>
          </dd>
        </div>
        <div v-if="selected.game_format && selected.game_format !== 'legacy'">
          <dt>{{ locale === 'he' ? 'שריון לכל שחקן' : 'Reservation per player' }}</dt>
          <dd>{{ selected.required_reserve }} 6B</dd>
        </div>
        <div v-if="selected.settlement?.transfer">
          <dt>{{ locale === 'he' ? 'סכום ההפסד ששולם' : 'Settled loss' }}</dt>
          <dd>{{ selected.settlement.transfer }} 6B</dd>
        </div>
        <div>
          <dt>{{ t('directPlay.rules') }}</dt>
          <dd>
            {{ t('directPlay.points', { count: selected.target_points }) }} ·
            {{
              t(
                selected.doubling_enabled
                  ? 'directPlay.withDoubling'
                  : 'directPlay.withoutDoubling',
              )
            }}
          </dd>
        </div>
        <div>
          <dt>{{ t('directPlay.monitor.clock') }}</dt>
          <dd>
            {{
              selected.time_control ? t(`directPlay.monitor.clocks.${selected.time_control}`) : '—'
            }}
          </dd>
        </div>
        <div>
          <dt>{{ t('directPlay.created') }}</dt>
          <dd>{{ date(selected.created_at) }}</dd>
        </div>
        <div>
          <dt>{{ t('directPlay.monitor.ended') }}</dt>
          <dd>{{ date(selected.completed_at) }}</dd>
        </div>
        <div>
          <dt>{{ t('tournaments.winner') }}</dt>
          <dd>{{ selected.winner ?? '—' }}</dd>
        </div>
      </dl>
      <p class="monitor-hint">{{ t('directPlay.monitor.resultHint') }}</p>
      <div class="monitor-player-actions">
        <RouterLink v-if="selected.host_id" :to="`/users/${selected.host_id}/edit`">{{
          t('directPlay.monitor.managePlayer', { name: selected.host ?? '' })
        }}</RouterLink>
        <RouterLink v-if="selected.guest_id" :to="`/users/${selected.guest_id}/edit`">{{
          t('directPlay.monitor.managePlayer', { name: selected.guest ?? '' })
        }}</RouterLink>
      </div>
      <Button
        v-if="bucket(selected) !== 'history'"
        :label="t('directPlay.cancelAndRefund')"
        severity="danger"
        outlined
        @click="() => {
          if (selected) emit('cancel', selected)
          selectedId = null
        }"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.direct-monitor {
  margin-bottom: 20px;
}
.monitor-toolbar,
.monitor-match header,
.monitor-match footer,
.monitor-matchup,
.monitor-scopes,
.monitor-player-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.monitor-toolbar,
.monitor-match header {
  justify-content: space-between;
}
.monitor-toolbar,
.monitor-hint,
dt {
  color: var(--p-text-muted-color);
  font-size: 0.85rem;
}
.monitor-scopes,
.monitor-filters {
  margin-block: 18px;
}
.monitor-filters {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(160px, 0.4fr);
  gap: 12px;
}
.monitor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr));
  gap: 16px;
}
.monitor-match {
  min-width: 0;
  padding: 18px;
  border: 1px solid var(--p-content-border-color);
  border-radius: 12px;
  display: grid;
  gap: 16px;
}
.monitor-matchup {
  justify-content: center;
  padding-block: 12px;
  overflow-wrap: anywhere;
}
.monitor-matchup :deep(.text-zinc-700) {
  color: var(--p-text-color);
}
.monitor-match header strong {
  font-size: 0.9rem;
}
.monitor-match footer {
  margin-top: auto;
}
.monitor-waiting {
  color: var(--p-text-muted-color);
}
.monitor-empty {
  text-align: center;
  padding: 40px 12px;
  color: var(--p-text-muted-color);
}
.monitor-details {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin-block: 24px;
}
.monitor-details dd {
  margin: 5px 0 0;
  overflow-wrap: anywhere;
}
.monitor-player-actions {
  margin-block: 20px;
}
.monitor-player-actions a {
  color: var(--p-primary-color);
  text-decoration: underline;
}
@media (max-width: 600px) {
  .monitor-filters,
  .monitor-details {
    grid-template-columns: 1fr;
  }
}
</style>
