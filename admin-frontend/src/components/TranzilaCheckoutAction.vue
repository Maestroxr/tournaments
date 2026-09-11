<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Button from 'primevue/button'
import { useI18n } from '@/i18n'
import { apiFetch, formatApiError } from '@/services/api'

interface PaymentSession {
  method: 'POST'
  action: string
  fields: Record<string, string>
  environment: 'test' | 'live'
}

const props = defineProps<{ checkoutId: string }>()
const { locale } = useI18n()
const busy = ref(false)
const error = ref('')
const session = ref<PaymentSession | null>(null)
let sequence = 0
const labels = computed(() => locale.value === 'he' ? {
  prepare: 'הכנת תשלום ב־Tranzila', open: 'פתיחת דף תשלום מאובטח',
  test: 'סביבת בדיקות — תשלום לבדיקה', live: 'סביבת ייצור — חיוב בכסף אמיתי',
  invalid: 'כתובת או פרטי דף התשלום אינם תקינים.',
  note: 'דף התשלום ייפתח בלשונית חדשה. יש לבדוק את הסכום והמשתמש לפני אישור התשלום.',
} : {
  prepare: 'Prepare Tranzila payment', open: 'Open secure payment page',
  test: 'Test environment — test payment', live: 'Live environment — real money payment',
  invalid: 'Invalid payment page address or details.',
  note: 'The payment page opens in a new tab. Check the amount and user before confirming payment.',
})

watch(() => props.checkoutId, () => {
  sequence++
  busy.value = false
  error.value = ''
  session.value = null
})

function isValid(value: PaymentSession) {
  try {
    const url = new URL(value.action)
    return url.origin === 'https://directng.tranzila.com' && url.pathname.startsWith('/') &&
      !url.username && !url.password && value.method === 'POST' &&
      ['test', 'live'].includes(value.environment) && value.fields !== null &&
      typeof value.fields === 'object' && !Array.isArray(value.fields) &&
      Object.values(value.fields).every(field => typeof field === 'string')
  } catch { return false }
}

async function prepare() {
  if (busy.value) return
  const current = ++sequence
  busy.value = true
  error.value = ''
  session.value = null
  try {
    const result = await apiFetch<PaymentSession>(`/api/admin/checkouts/${encodeURIComponent(props.checkoutId)}/session`, { method: 'POST' })
    if (current !== sequence) return
    if (!isValid(result)) throw new Error(labels.value.invalid)
    session.value = result
  } catch (caught) {
    if (current === sequence) error.value = formatApiError(caught)
  } finally {
    if (current === sequence) busy.value = false
  }
}
</script>

<template>
  <div class="checkout-action" :aria-busy="busy">
    <Button v-if="!session" type="button" :label="labels.prepare" :loading="busy" :disabled="busy" @click="prepare" />
    <p v-if="error" role="alert" class="mt-2 text-red-400">{{ error }}</p>
    <template v-if="session">
      <p role="status" class="font-semibold" :class="session.environment === 'live' ? 'text-amber-300' : 'text-sky-300'">{{ labels[session.environment] }}</p>
      <p class="my-2 text-sm">{{ labels.note }}</p>
      <form :action="session.action" method="POST" target="_blank" rel="noopener noreferrer">
        <input v-for="(value, key) in session.fields" :key="key" type="hidden" :name="key" :value="value" />
        <Button type="submit" :label="labels.open" icon="bi bi-box-arrow-up-right" />
      </form>
    </template>
  </div>
</template>

<style scoped>
.checkout-action { min-width: 200px; max-width: 320px; }
</style>
