<script setup lang="ts">
import { computed, ref } from 'vue'
import { apiFetch, formatApiError } from '@/services/api'
import { useI18n } from '@/i18n'
interface Refund { id: number; amount: string; provider_reference: string; actor: string; created_at: string; adjusted_at: string | null; adjustment_reference: string; adjusted_by: string | null }
const props = defineProps<{ checkoutId: string; status: string; transactionIndex?: string; refunds?: Refund[]; canManage: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const { locale } = useI18n()
const labels = computed(() => locale.value === 'he' ? {
  reconcile: 'בירור מול הספק', index: 'אינדקס עסקה', refund: 'רישום החזר שבוצע', amount: 'סכום ההחזר במטבע הרכישה', ref: 'אסמכתת ההחזר אצל הספק',
  confirmed: 'בדקתי שההחזר בוצע ואושר אצל הספק', save: 'שמירת רישום החזר',
  note: 'הרישום אינו שולח החזר כספי ואינו משנה קויינס או תקופת מנוי. יש להשלים התאמה מבוקרת ולתעד אותה בנפרד.',
  pending: 'ממתין להתאמת ארנק/מנוי', adjusted: 'תועדה התאמת ארנק/מנוי', adjustment: 'אסמכתת התאמה פנימית',
  attest: 'ההתאמה נבדקה והושלמה, כולל השפעה על מנויים נוספים וקויינס שנוצלו', complete: 'תיעוד השלמת ההתאמה', done: 'הפעולה הושלמה',
} : {
  reconcile: 'Reconcile with provider', index: 'Transaction index', refund: 'Record completed external refund', amount: 'Refund amount in purchase currency', ref: 'Provider refund reference',
  confirmed: 'I verified the refund was completed and approved by the provider', save: 'Save refund record',
  note: 'Recording does not send a refund or change coins or membership dates. Complete a reviewed fulfillment adjustment and record it separately.',
  pending: 'Wallet/membership adjustment pending', adjusted: 'Wallet/membership adjustment recorded', adjustment: 'Internal adjustment reference',
  attest: 'Adjustment reviewed and completed, including other memberships and spent coins', complete: 'Record completed adjustment', done: 'Action completed',
})
const index = ref(props.transactionIndex || ''), amount = ref(''), providerRef = ref(''), confirmed = ref(false)
const busy = ref(false), error = ref(''), success = ref('')
const adjustments = ref<Record<number, string>>({}), attested = ref<Record<number, boolean>>({})
let retry: { payload: string; key: string } | null = null
async function post(path: string, body: object) {
  if (busy.value) return false
  busy.value = true; error.value = ''; success.value = ''
  try { await apiFetch(path, { method: 'POST', body: JSON.stringify(body) }); success.value = labels.value.done; emit('changed'); return true }
  catch (e) { error.value = formatApiError(e); return false }
  finally { busy.value = false }
}
async function refund() {
  const payload = JSON.stringify({ amount: amount.value, provider_reference: providerRef.value, confirmed_in_provider: confirmed.value })
  if (retry?.payload !== payload) retry = { payload, key: crypto.randomUUID() }
  if (await post(`/api/admin/checkouts/${props.checkoutId}/refunds`, { ...JSON.parse(payload), idempotency_key: retry.key })) {
    retry = null; amount.value = ''; providerRef.value = ''; confirmed.value = false
  }
}
</script>

<template>
  <div class="review">
    <p v-if="error" role="alert">{{ error }}</p><p v-if="success" role="status">{{ success }}</p>
    <form v-if="canManage && ['pending', 'paid'].includes(status)" @submit.prevent="post(`/api/admin/checkouts/${checkoutId}/reconcile`, { transaction_index: Number(index) })">
      <label>{{ labels.index }}<input v-model="index" inputmode="numeric" pattern="[0-9]{1,12}" required /></label>
      <button :disabled="busy || !index">{{ labels.reconcile }}</button>
    </form>
    <details v-if="canManage && status === 'paid' && transactionIndex">
      <summary>{{ labels.refund }}</summary><p>{{ labels.note }}</p>
      <form @submit.prevent="refund">
        <label>{{ labels.amount }}<input v-model="amount" type="number" min="0.01" max="99999999.99" step="0.01" required /></label>
        <label>{{ labels.ref }}<input v-model="providerRef" required maxlength="100" /></label>
        <label><input v-model="confirmed" type="checkbox" required />{{ labels.confirmed }}</label>
        <button :disabled="busy || !confirmed">{{ labels.save }}</button>
      </form>
    </details>
    <div v-for="r in refunds || []" :key="r.id">
      <p>{{ r.amount }} · {{ r.provider_reference }} · {{ r.actor }} · {{ new Date(r.created_at).toLocaleString(locale) }}</p>
      <strong>{{ r.adjusted_at ? labels.adjusted : labels.pending }}</strong>
      <p v-if="r.adjusted_at">{{ r.adjustment_reference }} · {{ r.adjusted_by }} · {{ new Date(r.adjusted_at).toLocaleString(locale) }}</p>
      <form v-else-if="canManage" @submit.prevent="post(`/api/admin/checkouts/${checkoutId}/refunds/${r.id}/adjustment`, { adjustment_reference: adjustments[r.id], adjustment_completed: attested[r.id] })">
        <label>{{ labels.adjustment }}<input v-model="adjustments[r.id]" required maxlength="100" /></label>
        <label><input v-model="attested[r.id]" type="checkbox" required />{{ labels.attest }}</label>
        <button :disabled="busy || !attested[r.id]">{{ labels.complete }}</button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.review { min-width: 220px; max-width: 400px; margin-top: 12px; } form, label { display: grid; gap: 6px; margin-block: 8px; }
input, button { color: #edf5ff; background: #101a2e; border: 1px solid #64748b; padding: 8px; border-radius: 6px; max-width: 100%; }
input[type=checkbox] { justify-self: start; } button:disabled { opacity: .5; } [role=alert] { color: #fca5a5; } [role=status] { color: #6ee7b7; }
</style>
