<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from '@/i18n'
import { apiFetch } from '@/services/api'

type IssueCode = 'configuration_missing' | 'library_missing' | 'worker_stopped' | 'failed' | 'retrying' | 'delayed'
interface Issue { code: IssueCode; count?: number; fields?: string[] }
interface Health { issues: Issue[]; checked_at: string; last_worker_seen_at: string | null }
const { locale } = useI18n()
const health = ref<Health | null>(null)
const failed = ref(false)
const busy = ref(false)
let disposed = false
let timer: ReturnType<typeof setInterval> | undefined
const copy = computed(() => locale.value === 'he' ? {
  title: 'התראות לטלפון — נדרשת בדיקה', refresh: 'בדיקה מחדש',
  error: 'לא ניתן לבדוק כרגע את מצב התראות הטלפון. נסה שוב.',
  note: 'הבדיקה מבוססת על מצב השרת ותור השליחה; היא אינה מאשרת קבלה בטלפון.',
  configuration_missing: 'חסרות הגדרות התראות בשרת. יש להשלים את ההגדרות הבאות:',
  library_missing: 'ספריית שליחת ההתראות חסרה בשרת. יש להתקין את דרישות הפרויקט.',
  worker_stopped: 'שירות שליחת ההתראות אינו מדווח פעילות. יש לבדוק שהוא פועל בשרת.',
  failed: 'התראות שלא נשלחו לאחר כל ניסיונות השליחה:',
  retrying: 'התראות שהחלו ניסיונות שליחה וטרם נשלחו:',
  delayed: 'התראות שממתינות לשליחה באיחור של יותר משתי דקות:',
} : {
  title: 'Phone notifications — review needed', refresh: 'Check again',
  error: 'Phone notification status could not be checked. Please try again.',
  note: 'This checks server activity and the delivery queue; it does not confirm receipt on a phone.',
  configuration_missing: 'Server push settings are missing. Configure these settings:',
  library_missing: 'The push delivery library is missing. Install the project requirements on the server.',
  worker_stopped: 'The push worker is not reporting activity. Check that it is running on the server.',
  failed: 'Notifications not sent after all delivery attempts:',
  retrying: 'Notifications with delivery attempts that have not yet been sent:',
  delayed: 'Notifications overdue for delivery by more than two minutes:',
})

async function refresh() {
  if (busy.value) return
  busy.value = true
  try {
    const result = await apiFetch<Health>('/api/admin/push-health')
    if (!disposed) { health.value = result; failed.value = false }
  } catch {
    if (!disposed) { health.value = null; failed.value = true }
  } finally { busy.value = false }
}
onMounted(() => {
  void refresh()
  timer = setInterval(() => { if (document.visibilityState !== 'hidden') void refresh() }, 30000)
})
onUnmounted(() => { disposed = true; clearInterval(timer) })
</script>

<template>
  <section v-if="failed || health?.issues.length" role="alert" class="push-health-alert" :aria-busy="busy">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 class="font-semibold">{{ copy.title }}</h2>
      <button type="button" class="rounded border px-3 py-1 disabled:opacity-50" :disabled="busy" @click="refresh">{{ copy.refresh }}</button>
    </div>
    <p v-if="failed" class="mt-2">{{ copy.error }}</p>
    <ul v-else class="mt-2 list-inside list-disc space-y-1">
      <li v-for="issue in health?.issues" :key="issue.code">
        {{ copy[issue.code] }} <b v-if="issue.count !== undefined">{{ issue.count }}</b>
        <span v-if="issue.fields?.length" dir="ltr">{{ issue.fields.join(', ') }}</span>
      </li>
    </ul>
    <p class="mt-2 text-sm">{{ copy.note }}</p>
  </section>
</template>

<style scoped>
.push-health-alert {
  margin: 1rem;
  padding: 1rem;
  color: var(--p-text-color, #f8fafc);
  background: rgb(245 158 11 / 10%);
  border: 1px solid rgb(245 158 11 / 50%);
  border-radius: 0.75rem;
}
</style>
