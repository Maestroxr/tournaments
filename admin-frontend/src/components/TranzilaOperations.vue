<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { apiFetch, formatApiError } from '@/services/api'
import { useI18n } from '@/i18n'

interface Run { id: number; kind: string; status: string; started_at: string; finished_at: string | null; date_from: string; date_to: string; checked: number; recovered: number; issues: number }
interface Issue { id: number; transaction_index: string; code: string; checkout_id: string | null; last_seen_at: string }
interface State { can_manage: boolean; runs: Run[]; issue_count: number; issues: Issue[] }
const { locale } = useI18n()
const he = computed(() => locale.value === 'he')
const state = ref<State | null>(null), error = ref(''), busy = ref(false)
const resolution = ref<Record<number, string>>({})
const labels = computed(() => he.value ? {
  title: 'בדיקת ספק והתאמת עסקאות', check: 'בדיקת גישה חיה לדוחות', refresh: 'רענון',
  note: 'הבדיקה קוראת דוח מהספק ללא חיוב. הצלחה מעידה על גישה לדוחות במועד הבדיקה בלבד, ולא על תקינות כל מסלול התשלום.',
  runs: 'בדיקות וריצות אחרונות', empty: 'טרם בוצעה בדיקה', issues: 'חריגות פתוחות', reference: 'אסמכתת טיפול', resolve: 'סימון כטופל',
  review: 'יש לאמת את העסקה אצל הספק ולטפל ברישומים לפני סגירת חריגה.',
  success: 'הושלם', failed: 'נכשל', incomplete: 'כיסוי חלקי', interrupted: 'נקטע', running: 'בתהליך',
  health: 'גישה לדוחות', reconcile: 'התאמת עסקאות', checked: 'נבדקו', recovered: 'שוחזרו',
  unmatched_transaction: 'עסקה ללא הזמנה תואמת', terminal_mismatch: 'מסוף לא תואם', verification_failed: 'נדרש בירור תשלום או החזר',
  pending_unresolved: 'הזמנה ישנה ממתינה לבירור — אין אישור לכישלון התשלום',
} : {
  title: 'Provider checks and reconciliation', check: 'Check live report access', refresh: 'Refresh',
  note: 'Reads a provider report without charging. Success confirms report access at that time, not the complete payment flow.',
  runs: 'Recent checks and runs', empty: 'No check recorded yet', issues: 'Open issues', reference: 'Resolution reference', resolve: 'Mark reviewed',
  review: 'Verify the provider transaction and complete any local adjustments before resolving an issue.',
  success: 'Complete', failed: 'Failed', incomplete: 'Partial coverage', interrupted: 'Interrupted', running: 'Running',
  health: 'Report access', reconcile: 'Reconciliation', checked: 'Checked', recovered: 'Recovered',
  unmatched_transaction: 'Transaction without matching order', terminal_mismatch: 'Terminal mismatch', verification_failed: 'Payment or refund review required',
  pending_unresolved: 'Old pending order needs review — payment failure is not confirmed',
})
function label(value: string) { return (labels.value as Record<string, string>)[value] || value }
async function load() {
  try { state.value = await apiFetch<State>('/api/admin/tranzila-operations') }
  catch (e) { state.value = null; error.value = formatApiError(e) }
}
async function act(path: string, body?: object) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await apiFetch(path, { method: 'POST', ...(body ? { body: JSON.stringify(body) } : {}) }) }
  catch (e) { error.value = formatApiError(e) }
  finally { await load(); busy.value = false }
}
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => { void load(); timer = setInterval(() => { if (!busy.value && document.visibilityState !== 'hidden') void load() }, 30000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <section class="operations" :aria-busy="busy">
    <h3>{{ labels.title }}</h3><p>{{ labels.note }}</p>
    <button type="button" :disabled="busy" @click="error = ''; load()">{{ labels.refresh }}</button>
    <button v-if="state?.can_manage" type="button" :disabled="busy" @click="act('/api/admin/tranzila-health')">{{ labels.check }}</button>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="state">
      <h4>{{ labels.runs }}</h4><p v-if="!state.runs.length">{{ labels.empty }}</p>
      <ul><li v-for="run in state.runs" :key="run.id">
        {{ new Date(run.finished_at || run.started_at).toLocaleString(locale) }} · {{ label(run.kind) }} · <strong>{{ label(run.status) }}</strong>
        <template v-if="run.kind === 'reconcile'"> · {{ run.date_from }} – {{ run.date_to }} · {{ labels.checked }}: {{ run.checked }} · {{ labels.recovered }}: {{ run.recovered }} · {{ labels.issues }}: {{ run.issues }}</template>
      </li></ul>
      <h4>{{ labels.issues }}: {{ state.issue_count }}</h4><p v-if="state.issue_count">{{ labels.review }}</p>
      <ul><li v-for="issue in state.issues" :key="issue.id">
        {{ issue.transaction_index }} · {{ label(issue.code) }} <small>{{ issue.checkout_id }}</small>
        <form v-if="state.can_manage" @submit.prevent="act(`/api/admin/tranzila-issues/${issue.id}/resolve`, { resolution_reference: resolution[issue.id] })">
          <label>{{ labels.reference }} <input v-model="resolution[issue.id]" required maxlength="100" /></label>
          <button :disabled="busy || !resolution[issue.id]">{{ labels.resolve }}</button>
        </form>
      </li></ul>
    </template>
  </section>
</template>

<style scoped>
.operations { padding: 16px; margin-block: 16px; border: 1px solid #40506d; border-radius: 12px; background: #111a30; overflow-wrap: anywhere; }
h3, h4 { font-weight: 600; margin-block: 12px; } p, li { margin-block: 8px; } small { display: block; }
button, input { color: #edf5ff; background: #101a2e; border: 1px solid #64748b; border-radius: 6px; padding: 8px; margin: 4px; max-width: 100%; }
button:disabled { opacity: .5; } [role=alert] { color: #fca5a5; }
form { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
