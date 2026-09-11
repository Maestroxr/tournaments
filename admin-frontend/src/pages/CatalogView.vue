<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Button from 'primevue/button'
import { apiFetch, ApiError, formatApiError } from '@/services/api'
import { useI18n } from '@/i18n'
import { catalogMessages, capabilityNames, capabilityValues } from '@/i18n/catalog'

interface Product {
  id: number; name: string; kind: 'subscription' | 'coins'; tier: string; price: string;
  currency: string; coin_quantity: number; period_months: number; active: boolean;
  capabilities: Record<string, boolean | string>; version: number;
}
interface Catalog { items: Product[]; capability_schema: Record<string, (boolean | string)[]> }
const { locale } = useI18n()
const labels = computed(() => catalogMessages[locale.value])
const data = ref<Catalog>({ items: [], capability_schema: {} })
const tab = ref<'subscription' | 'coins'>('subscription')
const draft = ref<Product | null>(null)
const baseline = ref('')
const busy = ref(false), saving = ref(false), error = ref(''), success = ref(''), conflict = ref(false)
const products = computed(() => data.value.items.filter(item => item.kind === tab.value))
const dirty = computed(() => draft.value !== null && JSON.stringify(draft.value) !== baseline.value)
const valid = computed(() => {
  const item = draft.value
  if (!item || !item.name.trim() || !/^\d+(\.\d{1,2})?$/.test(String(item.price))) return false
  const price = Number(item.price)
  if (!Number.isFinite(price) || price < 0 || price > 99999999.99) return false
  if (item.tier === 'FREE' ? price !== 0 : item.active && price <= 0) return false
  return item.kind === 'coins'
    ? Number.isInteger(item.coin_quantity) && item.coin_quantity > 0 && item.coin_quantity <= 2147483647
    : [1, 3, 6, 12].includes(item.period_months)
})
function edit(item: Product) {
  draft.value = { ...item, capabilities: { ...item.capabilities } }
  baseline.value = JSON.stringify(draft.value)
  conflict.value = false; error.value = ''; success.value = ''
}
function create() {
  edit({ id: 0, name: '', kind: 'coins', tier: '', price: '0.00', currency: 'ILS', coin_quantity: 100, period_months: 0, active: false, capabilities: {}, version: 0 })
}
async function load() {
  busy.value = true; error.value = ''
  try { data.value = await apiFetch<Catalog>('/api/admin/store-catalog') }
  catch (e) { error.value = formatApiError(e) }
  finally { busy.value = false }
}
async function reloadProduct() {
  const id = draft.value?.id
  await load()
  if (!error.value) {
    const item = data.value.items.find(item => item.id === id)
    if (item) edit(item)
  }
}
async function save() {
  if (!valid.value || !draft.value || saving.value || conflict.value) return
  saving.value = true; error.value = ''; success.value = ''
  const item = draft.value
  const payload = { name: item.name.trim(), price: String(item.price), currency: item.currency,
    coin_quantity: item.kind === 'coins' ? item.coin_quantity : 0,
    period_months: item.kind === 'subscription' ? item.period_months : 0,
    active: item.active, capabilities: item.kind === 'subscription' ? item.capabilities : {},
    ...(item.id ? { version: item.version } : { kind: item.kind, tier: item.tier }) }
  try {
    await apiFetch(`/api/admin/store-catalog${item.id ? `/${item.id}` : ''}`, {
      method: item.id ? 'PATCH' : 'POST', body: JSON.stringify(payload),
    })
    draft.value = null; success.value = labels.value.saved
    await load()
  } catch (e) {
    conflict.value = e instanceof ApiError && e.status === 409
    error.value = conflict.value ? labels.value.conflict : formatApiError(e)
  } finally { saving.value = false }
}
function money(item: Product) { return new Intl.NumberFormat(locale.value, { style: 'currency', currency: item.currency }).format(Number(item.price)) }
function valueLabel(value: boolean | string) {
  return typeof value === 'boolean' ? value ? labels.value.enabled : labels.value.disabled : capabilityValues[value]?.[locale.value] ?? value
}
onMounted(load)
</script>

<template>
  <section class="catalog">
    <header class="heading"><div><h2>{{ labels.title }}</h2><p>{{ labels.subtitle }}</p></div><Button :label="labels.refresh" icon="bi bi-arrow-clockwise" outlined :loading="busy" :disabled="saving" @click="load" /></header>
    <aside class="notice">{{ labels.preparation }}</aside>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="success" role="status" class="success">{{ success }}</p>
    <div class="tabs" :aria-label="labels.title">
      <button type="button" :aria-pressed="tab === 'subscription'" @click="tab = 'subscription'">{{ labels.subscriptions }} <span>{{ data.items.filter(item => item.kind === 'subscription').length }}</span></button>
      <button type="button" :aria-pressed="tab === 'coins'" @click="tab = 'coins'">{{ labels.coins }} <span>{{ data.items.filter(item => item.kind === 'coins').length }}</span></button>
    </div>
    <div class="workspace">
      <div class="product-list" :aria-busy="busy">
        <Button v-if="tab === 'coins'" :label="labels.create" icon="bi bi-plus" :disabled="!!draft || busy" @click="create" />
        <p v-if="busy && !data.items.length" role="status">{{ labels.loading }}</p>
        <p v-else-if="!products.length" class="empty">{{ labels.empty }}</p>
        <div class="cards">
          <article v-for="item in products" :key="item.id" class="product" :class="{ selected: draft?.id === item.id }">
            <div class="product-top"><span class="eyebrow">{{ item.kind === 'subscription' ? item.tier : labels.coins }}</span><span class="badge" :class="{ active: item.active }">{{ item.active ? labels.active : labels.inactive }}</span></div>
            <h3>{{ item.name }}</h3>
            <p class="price">{{ item.tier === 'FREE' ? labels.free : money(item) }}</p>
            <p class="muted">{{ item.kind === 'coins' ? `${item.coin_quantity.toLocaleString(locale)} ${labels.coinUnit} · ${labels.perPackage}` : `${item.period_months} ${item.period_months === 1 ? labels.month : labels.months}` }}</p>
            <Button :label="labels.edit" outlined :disabled="!!draft" @click="edit(item)" />
          </article>
        </div>
      </div>
      <form v-if="draft" class="editor" @submit.prevent="save">
        <div class="heading"><h3>{{ draft.id ? labels.editing : labels.create }}</h3><small v-if="dirty">{{ labels.unsaved }}</small></div>
        <fieldset :disabled="saving || conflict">
          <label>{{ labels.name }}<input v-model="draft.name" required maxlength="100" /></label>
          <p v-if="draft.kind === 'subscription'" class="muted">{{ labels.tier }}: <strong>{{ draft.tier }}</strong><br />{{ labels.fixedTier }}</p>
          <div class="form-grid">
            <label>{{ labels.price }}<input v-model="draft.price" required type="number" :min="draft.active && draft.tier !== 'FREE' ? '0.01' : '0'" :max="draft.tier === 'FREE' ? '0' : '99999999.99'" step="0.01" :readonly="draft.tier === 'FREE'" /></label>
            <label>{{ labels.currency }}<select v-model="draft.currency"><option>ILS</option><option>USD</option><option>EUR</option></select></label>
          </div>
          <label v-if="draft.kind === 'coins'">{{ labels.quantity }}<input v-model.number="draft.coin_quantity" required type="number" min="1" max="2147483647" step="1" /></label>
          <label v-else>{{ labels.period }}<select v-model="draft.period_months"><option v-for="months in [1, 3, 6, 12]" :key="months" :value="months">{{ months }} {{ months === 1 ? labels.month : labels.months }}</option></select></label>
          <label class="checkbox"><input v-model="draft.active" type="checkbox" />{{ labels.available }}</label>
          <template v-if="draft.kind === 'subscription'">
            <h4>{{ labels.permissions }}</h4><p class="impact">{{ labels.impact }}</p>
            <div class="permissions">
              <label v-for="(values, key) in data.capability_schema" :key="key">{{ capabilityNames[key]?.[locale] ?? key }}<select v-model="draft.capabilities[key]"><option v-for="value in values" :key="String(value)" :value="value">{{ valueLabel(value) }}</option></select></label>
            </div>
          </template>
        </fieldset>
        <p v-if="!valid" class="muted">{{ labels.validation }}</p>
        <Button v-if="conflict" :label="labels.reload" :loading="busy" @click="reloadProduct" />
        <div class="actions"><Button type="submit" :label="labels.save" :loading="saving" :disabled="!valid || conflict" /><Button type="button" :label="labels.cancel" outlined :disabled="saving" @click="draft = null; conflict = false; error = ''" /></div>
      </form>
    </div>
  </section>
</template>

<style scoped>
.catalog { color: #dbe7f8; }
.heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
h2 { font-size: 1.5rem; font-weight: 700; } h3 { font-size: 1.15rem; font-weight: 600; } h4 { font-weight: 600; }
.heading p, .muted, .heading small { color: #a8bad3; font-size: .9rem; }
.notice { background: #11283b; border: 1px solid #285977; padding: 14px 18px; border-radius: 10px; margin-block: 20px; line-height: 1.7; }
.tabs { display: flex; gap: 8px; border-bottom: 1px solid #2a3851; padding-bottom: 12px; margin-bottom: 24px; }
.tabs button { border: 1px solid #33445f; padding: 10px 16px; border-radius: 8px; color: #bccae0; background: #111b2c; }
.tabs button[aria-pressed=true] { color: #e8f5ff; background: #244262; border-color: #588dbd; }
.tabs span { margin-inline-start: 8px; opacity: .7; }
.workspace { display: flex; align-items: flex-start; gap: 24px; flex-wrap: wrap; }
.product-list { flex: 1; min-width: min(100%, 280px); } .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); gap: 16px; margin-top: 16px; }
.product { border: 1px solid #2a3a56; border-radius: 14px; padding: 20px; background: #111a2c; }
.product.selected { border-color: #66b8f4; } .product h3 { margin-top: 18px; overflow-wrap: anywhere; }
.product-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.eyebrow { color: #90bcf2; font-size: .8rem; font-weight: 600; } .badge { padding: 3px 9px; border-radius: 16px; color: #b6c3d4; background: #283349; font-size: .75rem; }
.badge.active { background: #143c36; color: #92e5c4; } .price { font-size: 1.8rem; font-weight: 700; margin-top: 14px; }
.product .muted { margin-bottom: 20px; } .editor { flex: 0 1 480px; width: 100%; border: 1px solid #3b526f; border-radius: 14px; padding: 22px; background: #111b2e; }
fieldset { border: 0; padding: 0; margin-block: 18px; display: grid; gap: 16px; min-width: 0; } fieldset:disabled { opacity: .65; }
label { display: grid; gap: 6px; font-size: .875rem; } input, select { min-width: 0; width: 100%; padding: 10px; border: 1px solid #3b4d68; border-radius: 7px; background: #0c1527; color: #e4eefb; }
input:focus-visible, select:focus-visible, button:focus-visible { outline: 2px solid #77c9fc; outline-offset: 2px; } input[readonly] { opacity: .65; }
.form-grid, .permissions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.checkbox { display: flex; align-items: center; gap: 10px; } .checkbox input { width: 18px; height: 18px; accent-color: #79bfff; }
.impact { font-size: .85rem; line-height: 1.7; color: #e4c99a; } .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
.error { color: #fda4af; margin-block: 14px; } .success { color: #86efac; margin-block: 14px; } .empty { padding: 30px; color: #a8bad3; }
@media (max-width: 560px) { .form-grid, .permissions { grid-template-columns: 1fr; } .tabs button { flex: 1; padding: 10px; } .editor { padding: 16px; } }
</style>
