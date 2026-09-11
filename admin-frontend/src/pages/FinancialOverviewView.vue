<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Button from 'primevue/button'
import Card from 'primevue/card'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import SelectButton from 'primevue/selectbutton'
import AppAlert from '@/components/AppAlert.vue'
import { apiFetch, formatApiError } from '@/services/api'
import { useI18n } from '@/i18n'
import type { FinanceData, FinanceRangeDays, FinanceTrendPoint } from '@/types/finance'

const { locale, t } = useI18n()
const data = ref<FinanceData | null>(null)
const loading = ref(true)
const error = ref('')
const rangeDays = ref<FinanceRangeDays>(30)
const ranges = computed(() => [
  { value: 7 as const, label: t('finance.ranges.sevenDays') },
  { value: 30 as const, label: t('finance.ranges.thirtyDays') },
  { value: 90 as const, label: t('finance.ranges.ninetyDays') },
  { value: 0 as const, label: t('finance.ranges.all') },
])

const localeTag = computed(() => locale.value === 'he' ? 'he-IL' : 'en-US')
const summaryCards = computed(() => data.value ? [
  { key: 'revenue', label: t('finance.revenue'), value: data.value.summary.revenue, icon: 'bi-arrow-down-left', tone: 'positive' },
  { key: 'expenses', label: t('finance.expenses'), value: data.value.summary.expenses, icon: 'bi-arrow-up-right', tone: 'negative' },
  { key: 'net', label: t('finance.net'), value: data.value.summary.net, icon: 'bi-calculator', tone: Number(data.value.summary.net) >= 0 ? 'positive' : 'negative' },
  { key: 'outstanding', label: t('finance.outstanding'), value: data.value.summary.outstanding, icon: 'bi-clock-history', tone: Number(data.value.summary.outstanding) > 0 ? 'warning' : 'neutral' },
] : [])

const chartBounds = computed(() => {
  const values = (data.value?.trend ?? []).flatMap(point => [
    Number(point.revenue), Number(point.expenses), Number(point.net),
  ])
  const minimum = Math.min(0, ...values)
  const maximum = Math.max(0, ...values)
  return { minimum, maximum, span: maximum - minimum || 1 }
})

function chartX(index: number, length: number) {
  return length <= 1 ? 500 : 50 + (index / (length - 1)) * 900
}

function chartY(value: number) {
  const { minimum, span } = chartBounds.value
  return 225 - ((value - minimum) / span) * 185
}

function chartPoints(key: keyof Pick<FinanceTrendPoint, 'revenue' | 'expenses' | 'net'>) {
  const trend = data.value?.trend ?? []
  return trend.map((point, index) => `${chartX(index, trend.length)},${chartY(Number(point[key]))}`).join(' ')
}

const zeroLineY = computed(() => chartY(0))
const comparisonMax = computed(() => Math.max(
  1,
  ...(data.value?.tournaments ?? []).flatMap(item => [
    Number(item.revenue), Number(item.expenses), Math.abs(Number(item.net)),
  ]),
))

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await apiFetch<FinanceData>(`/api/admin/finance?days=${rangeDays.value}`)
  } catch (caught: unknown) {
    error.value = formatApiError(caught)
  } finally {
    loading.value = false
  }
}

async function selectRange(value: FinanceRangeDays | null) {
  if (value === null || rangeDays.value === value) return
  rangeDays.value = value
  await load()
}

function formatMoney(value: string) {
  return new Intl.NumberFormat(localeTag.value, {
    maximumFractionDigits: 2,
  }).format(Number(value)) + (locale.value === 'he' ? ' קויינס' : ' coins')
}

function formatDate(value: string) {
  return new Date(`${value}T00:00:00`).toLocaleDateString(localeTag.value, {
    day: 'numeric', month: 'short',
  })
}

function chartDateAt(index: number) {
  const point = data.value?.trend[index]
  return point ? formatDate(point.date) : ''
}

function barWidth(value: string) {
  return `${Math.max(2, (Math.abs(Number(value)) / comparisonMax.value) * 100)}%`
}

function chartPointLabel(label: string, point: FinanceTrendPoint, value: string) {
  return t('finance.chartPoint', {
    label,
    date: formatDate(point.date),
    value: formatMoney(value),
  })
}

onMounted(load)
</script>

<template>
  <section class="finance-overview" aria-labelledby="finance-heading">
    <header class="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 id="finance-heading" class="text-xl font-semibold text-black">{{ t('finance.title') }}</h2>
        <p class="mt-1 text-sm text-zinc-500">{{ t('finance.subtitle') }}</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <SelectButton :model-value="rangeDays" :options="ranges" option-label="label" option-value="value" :aria-label="t('finance.rangeAria')" @update:model-value="selectRange($event as FinanceRangeDays)" />
        <Button :label="t('common.refresh')" icon="bi bi-arrow-clockwise" size="small" severity="secondary" outlined :loading="loading" @click="load" />
      </div>
    </header>

    <AppAlert v-if="error" class="mb-4" type="error" :message="error" />
    <div v-if="loading && !data" class="grid grid-cols-2 gap-3 xl:grid-cols-4" :aria-label="t('finance.loading')">
      <div v-for="index in 4" :key="index" class="h-28 animate-pulse rounded-lg bg-zinc-100"></div>
    </div>

    <template v-else-if="data">
      <div class="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Card v-for="card in summaryCards" :key="card.key" :class="['finance-summary-card', `is-${card.tone}`]">
          <template #content>
            <div class="flex items-start justify-between gap-2">
              <span class="text-sm font-medium text-zinc-500">{{ card.label }}</span>
              <i :class="['bi', card.icon]" aria-hidden="true"></i>
            </div>
            <strong class="mt-3 block text-2xl font-bold text-black" dir="ltr">{{ formatMoney(card.value) }}</strong>
            <small v-if="card.key === 'expenses'" class="mt-1 block text-xs text-zinc-500">
              {{ t('finance.expenseBreakdown', { refunds: formatMoney(data.summary.refunds), prizes: formatMoney(data.summary.prizes) }) }}
            </small>
            <small v-else-if="card.key === 'outstanding'" class="mt-1 block text-xs text-zinc-500">{{ t('finance.outstandingHint', { count: data.summary.outstanding_count }) }}</small>
          </template>
        </Card>
      </div>

      <Card class="mt-5 finance-chart-card">
        <template #title>{{ t('finance.trendTitle') }}</template>
        <template #subtitle>{{ t('finance.trendSubtitle') }}</template>
        <template #content>
          <div v-if="data.trend.length" class="finance-chart" role="img" :aria-label="t('finance.trendAria')">
            <div class="mb-3 flex flex-wrap gap-4 text-xs font-medium text-zinc-500">
              <span><i class="finance-legend is-revenue" aria-hidden="true"></i>{{ t('finance.revenue') }}</span>
              <span><i class="finance-legend is-expenses" aria-hidden="true"></i>{{ t('finance.expenses') }}</span>
              <span><i class="finance-legend is-net" aria-hidden="true"></i>{{ t('finance.net') }}</span>
            </div>
            <svg viewBox="0 0 1000 250" preserveAspectRatio="none" aria-hidden="true">
              <line x1="50" x2="950" :y1="zeroLineY" :y2="zeroLineY" class="finance-chart__zero" />
              <polyline :points="chartPoints('revenue')" class="finance-chart__line is-revenue" />
              <polyline :points="chartPoints('expenses')" class="finance-chart__line is-expenses" />
              <polyline :points="chartPoints('net')" class="finance-chart__line is-net" />
              <g v-for="(point, index) in data.trend" :key="point.date">
                <circle :cx="chartX(index, data.trend.length)" :cy="chartY(Number(point.revenue))" r="4" class="finance-chart__point is-revenue"><title>{{ chartPointLabel(t('finance.revenue'), point, point.revenue) }}</title></circle>
                <circle :cx="chartX(index, data.trend.length)" :cy="chartY(Number(point.expenses))" r="4" class="finance-chart__point is-expenses"><title>{{ chartPointLabel(t('finance.expenses'), point, point.expenses) }}</title></circle>
                <circle :cx="chartX(index, data.trend.length)" :cy="chartY(Number(point.net))" r="4" class="finance-chart__point is-net"><title>{{ chartPointLabel(t('finance.net'), point, point.net) }}</title></circle>
              </g>
            </svg>
            <div class="mt-2 flex justify-between text-xs text-zinc-500" dir="ltr">
              <span>{{ chartDateAt(0) }}</span>
              <span>{{ chartDateAt(Math.floor(data.trend.length / 2)) }}</span>
              <span>{{ chartDateAt(data.trend.length - 1) }}</span>
            </div>
            <ul class="sr-only">
              <li v-for="point in data.trend" :key="point.date">
                {{ formatDate(point.date) }}: {{ t('finance.revenue') }} {{ formatMoney(point.revenue) }}, {{ t('finance.expenses') }} {{ formatMoney(point.expenses) }}, {{ t('finance.net') }} {{ formatMoney(point.net) }}
              </li>
            </ul>
          </div>
          <p v-else class="py-10 text-center text-sm text-zinc-500">{{ t('finance.noTrend') }}</p>
        </template>
      </Card>

      <Card class="mt-5">
        <template #title>{{ t('finance.tournamentComparison') }}</template>
        <template #subtitle>{{ t('finance.tournamentComparisonSubtitle') }}</template>
        <template #content>
          <DataTable :value="data.tournaments" data-key="id" striped-rows scrollable size="small">
            <template #empty>{{ t('finance.noTournaments') }}</template>
            <Column field="name" :header="t('transfers.tournament')">
              <template #body="{ data: tournament }">
                <RouterLink :to="`/tournaments/${tournament.id}/overview`" class="font-medium hover:underline" dir="auto">{{ tournament.name }}</RouterLink>
              </template>
            </Column>
            <Column :header="t('finance.revenue')">
              <template #body="{ data: tournament }"><span class="text-emerald-700" dir="ltr">{{ formatMoney(tournament.revenue) }}</span></template>
            </Column>
            <Column :header="t('finance.expenses')">
              <template #body="{ data: tournament }"><span class="text-red-700" dir="ltr">{{ formatMoney(tournament.expenses) }}</span></template>
            </Column>
            <Column :header="t('finance.net')">
              <template #body="{ data: tournament }">
                <div class="min-w-32">
                  <span :class="Number(tournament.net) >= 0 ? 'text-emerald-700' : 'text-red-700'" dir="ltr">{{ formatMoney(tournament.net) }}</span>
                  <span class="mt-1 block h-1.5 overflow-hidden rounded-full bg-zinc-100"><span :class="['block h-full rounded-full', Number(tournament.net) >= 0 ? 'bg-emerald-500' : 'bg-red-500']" :style="{ width: barWidth(tournament.net) }"></span></span>
                </div>
              </template>
            </Column>
          </DataTable>
        </template>
      </Card>

      <AppAlert v-if="data.ignored_transactions" class="mt-4" type="warning" :message="t('finance.ignoredTransactions', { count: data.ignored_transactions })" />
      <p class="mt-4 text-xs text-zinc-500"><i class="bi bi-info-circle me-1" aria-hidden="true"></i>{{ t('finance.accountingNote') }}</p>
    </template>
  </section>
</template>

<style scoped>
.finance-summary-card { border: 1px solid #263653; background: #111a30; }
.finance-summary-card :deep(.p-card-body),
.finance-summary-card :deep(.p-card-content) { height: 100%; padding: 0; }
.finance-summary-card :deep(.p-card-body) { padding: 16px; }
.finance-summary-card.is-positive i { color: #77d7bd; }
.finance-summary-card.is-negative i { color: #f39aaa; }
.finance-summary-card.is-warning i { color: #e7c978; }
.finance-summary-card.is-neutral i { color: #9fb2d0; }
.finance-chart-card :deep(.p-card-content) { overflow: hidden; }
.finance-chart svg { display: block; width: 100%; height: 260px; overflow: visible; }
.finance-chart__zero { stroke: #40506d; stroke-width: 1; stroke-dasharray: 5 6; }
.finance-chart__line { fill: none; stroke-width: 3; vector-effect: non-scaling-stroke; }
.finance-chart__line.is-revenue { stroke: #39b997; }
.finance-chart__line.is-expenses { stroke: #df7183; }
.finance-chart__line.is-net { stroke: #66a3ff; }
.finance-chart__point { stroke: #111a30; stroke-width: 2; vector-effect: non-scaling-stroke; }
.finance-chart__point.is-revenue { fill: #39b997; }
.finance-chart__point.is-expenses { fill: #df7183; }
.finance-chart__point.is-net { fill: #66a3ff; }
.finance-legend { display: inline-block; width: 9px; height: 9px; margin-inline-end: 6px; border-radius: 50%; }
.finance-legend.is-revenue { background: #39b997; }
.finance-legend.is-expenses { background: #df7183; }
.finance-legend.is-net { background: #66a3ff; }
@media (max-width: 640px) {
  .finance-chart svg { height: 190px; }
}
</style>
