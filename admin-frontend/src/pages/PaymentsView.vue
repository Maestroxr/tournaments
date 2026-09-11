<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Button from 'primevue/button'
import AutoComplete, { type AutoCompleteCompleteEvent } from 'primevue/autocomplete'
import { RouterLink } from 'vue-router'
import { apiFetch, formatApiError } from '@/services/api'
import { useI18n } from '@/i18n'
import { paymentMessages } from '@/i18n/payments'
import TranzilaReadiness from '@/components/TranzilaReadiness.vue'
import TranzilaCheckoutAction from '@/components/TranzilaCheckoutAction.vue'

const { locale } = useI18n()
const labels = computed(() => paymentMessages[locale.value])
const catalogLabels = computed(() => locale.value === 'he' ? {
  choose: 'בחרו מנוי או חבילת קויינס', manage: 'ניהול מנויים וחבילות קויינס',
  empty: 'אין מוצרים פעילים בתשלום. ניתן להוסיף אותם בניהול החבילות.',
  duration: 'משך המנוי בחודשים', loading: 'טוען חבילות…',
} : {
  choose: 'Choose a subscription or coin package', manage: 'Manage subscriptions and coin packages',
  empty: 'No active paid products. Add them in package management.',
  duration: 'Subscription duration in months', loading: 'Loading packages…',
})
type Status = 'draft' | 'pending' | 'paid' | 'failed' | 'cancelled' | 'refunded'
interface Row {
  id: string; username: string; actor: string; product: 'coins' | 'subscription'; tier: string
  amount: string; currency: string; coin_quantity: number; status: Status; environment: 'sandbox' | 'live'
  provider_reference: string | null; created_at: string
  events: { kind: string; actor: string | null; created_at: string }[]
}
interface Data {
  provider?: { checkout_enabled: boolean }
  count: number; items: Row[]; totals: { currency: string; environment: 'sandbox' | 'live'; amount: string; coins: number }[]
  legacy_count: number
  legacy_payments: { id: number; username: string; amount: string; currency: string; provider_reference: string; refunded_amount: string; reversed: boolean; created_at: string }[]
}
interface User { id: number; username: string }
interface CatalogProduct {
  id: number; name: string; kind: 'coins' | 'subscription'; tier: string
  price: string; currency: string; coin_quantity: number; period_months: number; active: boolean
}
const data = ref<Data | null>(null)
const error = ref(''), success = ref(''), busy = ref(false), saving = ref(false)
const query = ref(''), status = ref(''), product = ref(''), offset = ref(0)
const selectedUser = ref<User | string | null>(null), users = ref<User[]>([])
const catalog = ref<CatalogProduct[]>([]), catalogError = ref(''), catalogLoading = ref(false)
const selectedProductId = ref<number | ''>('')
const purchasableProducts = computed(() => catalog.value.filter(item => item.active && Number(item.price) > 0))
const selectedProduct = computed(() => purchasableProducts.value.find(item => item.id === selectedProductId.value))
const statuses: Status[] = ['draft', 'pending', 'paid', 'failed', 'cancelled', 'refunded']
let sequence = 0, searchSequence = 0
let retry: { payload: string; key: string } | null = null
const canSave = computed(() => selectedUser.value && typeof selectedUser.value === 'object' && selectedProduct.value && !catalogLoading.value && !catalogError.value)
async function loadCatalog() {
  catalogLoading.value = true; catalogError.value = ''
  try {
    const result = await apiFetch<{ items: CatalogProduct[] }>('/api/admin/store-catalog')
    catalog.value = result.items
    if (!selectedProduct.value) selectedProductId.value = ''
  } catch (e) { catalogError.value = formatApiError(e) }
  finally { catalogLoading.value = false }
}
async function searchUsers(event: AutoCompleteCompleteEvent) {
  const current = ++searchSequence
  try {
    const result = await apiFetch<User[]>(`/api/admin/users?q=${encodeURIComponent(event.query)}`)
    if (current === searchSequence) users.value = result
  } catch (e) { if (current === searchSequence) error.value = formatApiError(e) }
}
async function load(reset = false) {
  if (reset) offset.value = 0
  const current = ++sequence
  busy.value = true; error.value = ''
  try {
    const params = new URLSearchParams({ q: query.value, status: status.value, product: product.value, offset: String(offset.value) })
    const result = await apiFetch<Data>(`/api/admin/checkouts?${params}`)
    if (current === sequence) data.value = result
  } catch (e) { if (current === sequence) error.value = formatApiError(e) }
  finally { if (current === sequence) busy.value = false }
}
async function save() {
  if (!canSave.value || saving.value || typeof selectedUser.value !== 'object' || !selectedUser.value) return
  saving.value = true; error.value = ''; success.value = ''
  const payload = JSON.stringify({ user_id: selectedUser.value.id, catalog_product_id: selectedProductId.value })
  if (retry?.payload !== payload) retry = { payload, key: crypto.randomUUID() }
  try {
    await apiFetch('/api/admin/checkouts', { method: 'POST', body: JSON.stringify({ ...JSON.parse(payload), idempotency_key: retry.key }) })
    retry = null; selectedProductId.value = ''; success.value = labels.value.saved
    await load(true)
  } catch (e) { error.value = formatApiError(e) }
  finally { saving.value = false }
}
function money(amount: string, currency: string) { return new Intl.NumberFormat(locale.value, { style: 'currency', currency }).format(Number(amount)) }
function date(value: string) { return new Date(value).toLocaleString(locale.value) }
function page(delta: number) { offset.value += delta * 50; void load() }
onMounted(() => { void load(); void loadCatalog() })
</script>

<template>
  <section class="payments">
    <h2 class="text-xl font-semibold">{{ labels.title }}</h2>
    <RouterLink to="/transfers/catalog" class="mt-3 inline-block text-sky-300 underline">{{ catalogLabels.manage }}</RouterLink>
    <TranzilaReadiness />
    <aside v-if="!data?.provider?.checkout_enabled" class="notice"><strong>{{ labels.prep }}</strong><p>{{ labels.note }}</p><p>{{ labels.separation }}</p></aside>
    <p v-if="error" role="alert" class="text-red-400">{{ error }}</p>
    <p v-if="success" role="status" class="text-emerald-400">{{ success }}</p>
    <details class="panel">
      <summary>{{ labels.create }}</summary>
      <p v-if="catalogError" role="alert" class="text-red-400">{{ catalogError }}</p>
      <p v-if="catalogLoading" role="status">{{ catalogLabels.loading }}</p>
      <p v-else-if="!catalogError && !purchasableProducts.length">{{ catalogLabels.empty }}</p>
      <div class="fields mt-4">
        <RouterLink to="/transfers/catalog" class="text-sky-300 underline">{{ catalogLabels.manage }}</RouterLink>
        <Button type="button" :label="labels.refresh" :loading="catalogLoading" @click="loadCatalog" />
      </div>
      <form class="fields" @submit.prevent="save">
        <label>{{ labels.user }}<AutoComplete v-model="selectedUser" :suggestions="users" option-label="username" force-selection :aria-label="labels.user" @complete="searchUsers" /></label>
        <label>{{ labels.product }}<select v-model="selectedProductId" required :disabled="catalogLoading || !!catalogError">
          <option disabled value="">{{ catalogLabels.choose }}</option>
          <option v-for="item in purchasableProducts" :key="item.id" :value="item.id">{{ item.name }} · {{ money(item.price, item.currency) }}</option>
        </select></label>
        <template v-if="selectedProduct">
          <label>{{ labels.amount }}<output>{{ money(selectedProduct.price, selectedProduct.currency) }}</output></label>
          <label>{{ labels.currency }}<output>{{ selectedProduct.currency }}</output></label>
          <label v-if="selectedProduct.kind === 'coins'">{{ labels.quantity }}<output>{{ selectedProduct.coin_quantity }}</output></label>
          <template v-else>
            <label>{{ labels.tier }}<output>{{ selectedProduct.tier }}</output></label>
            <label>{{ catalogLabels.duration }}<output>{{ selectedProduct.period_months }}</output></label>
          </template>
        </template>
        <Button type="submit" :label="labels.save" :loading="saving" :disabled="!canSave" />
      </form>
    </details>
    <form class="fields panel" @submit.prevent="load(true)">
      <label>{{ labels.search }}<input v-model="query" type="search" /></label>
      <label>{{ labels.product }}<select v-model="product"><option value="">{{ labels.all }}</option><option value="coins">{{ labels.coins }}</option><option value="subscription">{{ labels.subscription }}</option></select></label>
      <label>{{ labels.status }}<select v-model="status"><option value="">{{ labels.all }}</option><option v-for="s in statuses" :key="s" :value="s">{{ labels[s] }}</option></select></label>
      <Button type="submit" :label="labels.refresh" :loading="busy" />
    </form>
    <template v-if="data">
      <div class="fields" :aria-busy="busy">
        <div v-for="total in data.totals" :key="total.currency + total.environment" class="panel">
          <p>{{ labels.income }} · {{ labels[total.environment] }}</p><strong>{{ money(total.amount, total.currency) }}</strong>
          <p>{{ labels.coins }}: {{ total.coins }}</p>
        </div>
      </div>
      <div class="table-wrap">
        <table><thead><tr><th>{{ labels.date }}</th><th>{{ labels.user }}</th><th>{{ labels.product }}</th><th>{{ labels.amount }}</th><th>{{ labels.quantity }}</th><th>{{ labels.status }}</th><th>{{ labels.actor }}</th><th>{{ labels.history }}</th></tr></thead>
          <tbody><tr v-for="row in data.items" :key="row.id">
            <td>{{ date(row.created_at) }}</td><td>{{ row.username }}</td><td>{{ labels[row.product] }} {{ row.tier }}</td>
            <td>{{ money(row.amount, row.currency) }}</td><td>{{ row.coin_quantity || '—' }}</td>
            <td>{{ labels[row.status] }}<small>{{ labels[row.environment] }}</small><TranzilaCheckoutAction v-if="data.provider?.checkout_enabled && (row.status === 'draft' || row.status === 'pending')" :checkout-id="row.id" /></td><td>{{ row.actor }}</td>
            <td><details><summary>{{ labels.history }}</summary><p>{{ row.id }}</p><p>{{ labels.reference }}: {{ row.provider_reference || '—' }}</p><p v-for="(event, index) in row.events" :key="index">{{ date(event.created_at) }} · {{ event.kind === 'draft_created' ? labels.draft_created : event.kind }} · {{ event.actor || '—' }}</p></details></td>
          </tr><tr v-if="!data.items.length"><td colspan="8">{{ labels.empty }}</td></tr></tbody>
        </table>
      </div>
      <h3 class="mt-6 font-semibold">{{ labels.legacy }}</h3><p>{{ labels.legacyNote }}</p>
      <div class="table-wrap"><table><thead><tr><th>{{ labels.date }}</th><th>{{ labels.user }}</th><th>{{ labels.amount }}</th><th>{{ labels.refunds }}</th><th>{{ labels.status }}</th><th>{{ labels.reference }}</th></tr></thead><tbody>
        <tr v-for="row in data.legacy_payments" :key="row.id"><td>{{ date(row.created_at) }}</td><td>{{ row.username }}</td><td>{{ money(row.amount, row.currency) }}</td><td>{{ money(row.refunded_amount, row.currency) }}</td><td>{{ row.reversed ? labels.cancelled : Number(row.refunded_amount) > 0 ? labels.refunded : labels.paid }}</td><td>{{ row.provider_reference }}</td></tr>
        <tr v-if="!data.legacy_payments.length"><td colspan="6">{{ labels.empty }}</td></tr>
      </tbody></table></div>
      <nav class="fields mt-4"><Button :label="labels.previous" :disabled="busy || offset === 0" @click="page(-1)" /><Button :label="labels.next" :disabled="busy || offset + 50 >= Math.max(data.count, data.legacy_count)" @click="page(1)" /></nav>
    </template>
  </section>
</template>

<style scoped>
.payments { color: #dbe7f8; }
.notice, .panel { padding: 16px; margin-block: 16px; border: 1px solid #263653; border-radius: 12px; background: #111a30; }
.notice { border-color: #2a7094; }
.notice p { margin-top: 8px; }
.fields { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; }
label { display: grid; gap: 6px; font-size: 14px; }
input, select { border: 1px solid #40506d; border-radius: 6px; padding: 9px; color: #edf5ff; background: #101a2e; max-width: 100%; }
input:focus-visible, select:focus-visible, summary:focus-visible { outline: 2px solid #62c7ef; outline-offset: 2px; }
summary { cursor: pointer; }
form.fields { margin-top: 16px; }
.table-wrap { overflow-x: auto; margin-top: 16px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { padding: 12px; text-align: start; border-bottom: 1px solid #263653; vertical-align: top; }
th { white-space: nowrap; background: #111a30; }
small { display: block; color: #b9c9e1; }
td details { min-width: 120px; overflow-wrap: anywhere; }
</style>
