<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Button from 'primevue/button'
import { useI18n } from '@/i18n'
import { apiFetch, formatApiError } from '@/services/api'

interface Readiness {
  ready: boolean
  enabled: boolean
  environment: 'test' | 'live'
  checks: { key: string; configured: boolean }[]
  automatic_fulfillment: boolean
  recurring_enabled: boolean
}

const { locale } = useI18n()
const data = ref<Readiness | null>(null)
const busy = ref(false)
const error = ref('')
const labels = computed(() => locale.value === 'he' ? {
  title: 'מוכנות לחיבור Tranzila', refresh: 'רענון הגדרות', loading: 'בודק הגדרות חיבור…',
  disabled: 'החיבור כבוי', ready: 'מוכן לבדיקת מסוף', missing: 'חסרות הגדרות חיבור',
  configured: 'מוגדר', absent: 'חסר', environment: 'סביבת חיבור', test: 'בדיקות', live: 'ייצור',
  notice: 'הבדיקה מציגה הגדרות בלבד. נדרש אימות מול Tranzila ובדיקת תשלום מקצה לקצה לפני הפעלה בייצור.',
  fulfillment: 'זיכוי קויינס והפעלת מנוי אוטומטיים ממתינים להשלמת אימות תשלום מול Tranzila.',
  recurring: 'המנויים משולמים פעם אחת לתקופה קבועה, ללא חידוש אוטומטי.',
  checks: { enabled: 'הפעלת החיבור', terminal: 'מסוף', api_key: 'מפתח API', api_secret: 'סוד API', return_url: 'כתובת חזרה מהתשלום', notify_url: 'כתובת לקבלת הודעות תשלום', report_mapping: 'אישור מיפוי שדות דוח העסקאות', transaction_status: 'ערך סטטוס עסקה מאושר מול הספק' } as Record<string, string>,
} : {
  title: 'Tranzila connection readiness', refresh: 'Refresh settings', loading: 'Checking connection settings…',
  disabled: 'Connection disabled', ready: 'Ready for terminal testing', missing: 'Connection settings missing',
  configured: 'Configured', absent: 'Missing', environment: 'Connection environment', test: 'Test', live: 'Live',
  notice: 'This checks configuration only. Provider validation and an end-to-end payment test are required before production use.',
  fulfillment: 'Automatic coin credit and subscription activation await payment verification with Tranzila.',
  recurring: 'Memberships are paid once for a fixed duration, without automatic renewal.',
  checks: { enabled: 'Connection enabled', terminal: 'Terminal', api_key: 'API key', api_secret: 'API secret', return_url: 'Payment return URL', notify_url: 'Payment notification URL', report_mapping: 'Transaction report field mapping confirmed', transaction_status: 'Provider-confirmed approved transaction status' } as Record<string, string>,
})
const status = computed(() => !data.value?.enabled ? labels.value.disabled : data.value.ready ? labels.value.ready : labels.value.missing)

async function refresh() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  data.value = null
  try {
    data.value = await apiFetch<Readiness>('/api/admin/tranzila-readiness')
  } catch (caught) {
    error.value = formatApiError(caught)
  } finally {
    busy.value = false
  }
}
onMounted(refresh)
</script>

<template>
  <section class="tranzila-readiness" :aria-busy="busy">
    <header class="flex flex-wrap items-center justify-between gap-3">
      <h3 class="text-lg font-semibold">{{ labels.title }}</h3>
      <Button type="button" :label="labels.refresh" icon="bi bi-arrow-clockwise" :loading="busy" :disabled="busy" @click="refresh" />
    </header>
    <p v-if="busy" role="status" class="mt-3">{{ labels.loading }}</p>
    <p v-if="error" role="alert" class="mt-3 text-red-400">{{ error }}</p>
    <template v-if="data">
      <p role="status" class="mt-3 font-semibold">{{ status }}</p>
      <p class="mt-2">{{ labels.environment }}: {{ labels[data.environment] }}</p>
      <dl class="checks">
        <div v-for="check in data.checks" :key="check.key">
          <dt>{{ labels.checks[check.key] || check.key }}</dt>
          <dd :class="check.configured ? 'text-emerald-300' : 'text-amber-300'">{{ check.configured ? labels.configured : labels.absent }}</dd>
        </div>
      </dl>
      <p v-if="!data.automatic_fulfillment" class="mt-3 text-sm">{{ labels.fulfillment }}</p>
      <p v-if="!data.recurring_enabled" class="mt-2 text-sm">{{ labels.recurring }}</p>
    </template>
    <p class="mt-3 text-sm text-slate-300">{{ labels.notice }}</p>
  </section>
</template>

<style scoped>
.tranzila-readiness { padding: 16px; margin-block: 16px; border: 1px solid #263653; border-radius: 12px; background: #111a30; color: #dbe7f8; }
.checks { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin-top: 16px; }
.checks > div { display: flex; justify-content: space-between; gap: 12px; padding: 10px; border: 1px solid #31425f; border-radius: 6px; }
</style>
