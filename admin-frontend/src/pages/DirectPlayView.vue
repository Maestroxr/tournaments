<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import AppAlert from '@/components/AppAlert.vue'
import DirectPlayMonitor from '@/components/DirectPlayMonitor.vue'
import GamesSidebar from '@/components/GamesSidebar.vue'
import GameSettingsPanel from '@/components/game-settings/GameSettingsPanel.vue'
import { useGameAdminSettings } from '@/composables/useGameAdminSettings'
import { settingsSections, type GamesSection, type SettingsSection } from '@/types/gameSettings'
import type {
  DirectPlaySettings,
  DirectPlayTable,
  DirectPlayTablesResponse,
} from '@/types/directPlay'
import { apiFetch, formatApiError } from '@/services/api'
import { useI18n } from '@/i18n'

const { t } = useI18n()
const route = useRoute()
const {
  form: settings,
  dirty,
  errors,
  fieldErrors,
  saved,
  savingSection,
  accept,
  save,
} = useGameAdminSettings()
const activeSection = computed<GamesSection>(() => {
  const raw = route.query.section
  const section = raw === 'quick' ? 'money' : raw === 'formats' ? 'match' : raw
  return typeof section === 'string' && settingsSections.includes(section as SettingsSection)
    ? (section as SettingsSection)
    : 'monitor'
})
const editSection = computed(() => (activeSection.value === 'monitor' ? null : activeSection.value))
const tables = ref<DirectPlayTable[]>([])
const loading = ref(false)
const refreshing = ref(false)
const monitorError = ref('')
const loadError = ref('')
const updatedAt = ref<string | null>(null)
const historyTotal = ref(0)
const cancellingId = ref<number | null>(null)
const pendingCancellation = ref<DirectPlayTable | null>(null)
const cancellationError = ref('')
const success = ref('')
let tablesRevision = 0
let live = true
let refreshTimer: ReturnType<typeof setInterval> | undefined
function setTables(response: DirectPlayTablesResponse) {
  tables.value = response.tables
  historyTotal.value =
    response.history_total ??
    response.tables.filter((table) => ['completed', 'cancelled'].includes(table.status)).length
  updatedAt.value = new Date().toISOString()
}
async function load() {
  if (loading.value || savingSection.value) return
  loading.value = true
  loadError.value = ''
  const revision = ++tablesRevision
  try {
    const [nextSettings, response] = await Promise.all([
      apiFetch<DirectPlaySettings>('/api/admin/direct-play/settings'),
      apiFetch<DirectPlayTablesResponse>('/api/admin/direct-play/tables'),
    ])
    if (!live || revision !== tablesRevision) return
    accept(nextSettings)
    setTables(response)
  } catch (error) {
    if (live) loadError.value = formatApiError(error)
  } finally {
    if (live) loading.value = false
  }
}
async function refreshTables() {
  if (refreshing.value || loading.value || cancellingId.value !== null) return
  refreshing.value = true
  const revision = tablesRevision
  try {
    const response = await apiFetch<DirectPlayTablesResponse>('/api/admin/direct-play/tables')
    if (!live || revision !== tablesRevision) return
    setTables(response)
    monitorError.value = ''
  } catch (error) {
    if (live) monitorError.value = formatApiError(error)
  } finally {
    if (live) refreshing.value = false
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
      '/api/admin/direct-play/tables/' + table.id + '/cancel',
      { method: 'POST' },
    )
    if (!live) return
    tablesRevision++
    const index = tables.value.findIndex((item) => item.id === table.id)
    if (index >= 0) tables.value[index] = updated
    pendingCancellation.value = null
    success.value = t('directPlay.tableCancelled')
  } catch (error) {
    if (live) cancellationError.value = formatApiError(error)
  } finally {
    if (live) cancellingId.value = null
  }
}
const hasDirty = computed(() => Object.values(dirty.value).some(Boolean))
function preventUnload(event: BeforeUnloadEvent) {
  if (!hasDirty.value) return
  event.preventDefault()
  event.returnValue = ''
}
onBeforeRouteLeave(() => !hasDirty.value || window.confirm(t('gameSettings.unsavedLeave')))
onMounted(() => {
  void load()
  window.addEventListener('beforeunload', preventUnload)
  refreshTimer = setInterval(() => {
    if (document.visibilityState === 'visible') void refreshTables()
  }, 15000)
})
onUnmounted(() => {
  live = false
  tablesRevision++
  clearInterval(refreshTimer)
  window.removeEventListener('beforeunload', preventUnload)
})
</script>
<template>
  <section aria-labelledby="direct-play-heading" class="space-y-6 text-neutral-100">
    <header class="flex flex-wrap items-center justify-between gap-4">
      <div>
        <h1 id="direct-play-heading" class="text-2xl font-bold">{{ t('gameSettings.title') }}</h1>
        <p class="mt-2 text-sm text-neutral-400">{{ t('gameSettings.subtitle') }}</p>
      </div>
      <Button
        :label="t('common.refresh')"
        icon="bi bi-arrow-clockwise"
        severity="secondary"
        outlined
        :loading="loading"
        :disabled="Boolean(savingSection)"
        @click="load"
      />
    </header>
    <AppAlert v-if="loadError" type="error" :message="loadError" />
    <AppAlert v-if="success" type="success" :message="success" dismissible @close="success = ''" />
    <div class="grid min-w-0 gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
      <GamesSidebar :active="activeSection" :dirty="dirty" />
      <div class="min-w-0">
        <p v-if="loading && !settings" role="status" class="p-6 text-neutral-400">
          {{ t('directPlay.loading') }}
        </p>
        <template v-if="settings">
          <div v-show="activeSection === 'monitor'" id="games-monitor">
            <AppAlert v-if="monitorError" type="error" :message="monitorError" />
            <DirectPlayMonitor
              :tables="tables"
              :refreshing="refreshing"
              :updated-at="updatedAt"
              :history-total="historyTotal"
              @refresh="refreshTables"
              @cancel="requestCancellation"
            />
          </div>
          <form
            v-if="editSection"
            :id="'games-' + editSection"
            class="space-y-6 rounded-xl border border-white/15 bg-neutral-950 p-4 sm:p-6"
            :aria-busy="savingSection === editSection"
            @submit.prevent="save(editSection)"
          >
            <header class="space-y-2">
              <h2 class="text-xl font-bold text-[#dfbc7c]">
                {{ t('gameSettings.sections.' + editSection) }}
              </h2>
              <p class="text-sm leading-relaxed text-neutral-400">
                {{ t('gameSettings.hints.' + editSection) }}
              </p>
            </header>
            <fieldset :disabled="savingSection === editSection" class="min-w-0">
              <legend class="sr-only">{{ t('gameSettings.sections.' + editSection) }}</legend>
              <GameSettingsPanel
                v-model="settings"
                :section="editSection"
                :errors="fieldErrors[editSection] ?? {}"
              />
            </fieldset>
            <AppAlert
              v-if="errors[editSection]"
              type="error"
              :message="errors[editSection] ?? ''"
            />
            <p
              v-if="saved[editSection] && !dirty[editSection]"
              role="status"
              class="text-sm text-green-300"
            >
              {{ t('directPlay.settingsSaved') }}
            </p>
            <footer
              class="flex flex-wrap items-center justify-between gap-4 border-t border-white/15 pt-4"
            >
              <p role="status" class="text-sm text-neutral-400">
                {{ t(dirty[editSection] ? 'gameSettings.unsaved' : 'gameSettings.upToDate') }}
              </p>
              <button
                type="submit"
                :disabled="!dirty[editSection] || Boolean(savingSection)"
                class="min-h-11 rounded-lg bg-[#dfbc7c] px-5 py-2 font-semibold text-black hover:bg-[#edce97] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#dfbc7c] disabled:cursor-default disabled:opacity-40"
              >
                {{
                  t(savingSection === editSection ? 'common.saving' : 'gameSettings.saveSection')
                }}
              </button>
            </footer>
          </form>
        </template>
      </div>
    </div>
    <Dialog
      :visible="Boolean(pendingCancellation)"
      modal
      :header="t('directPlay.cancelTitle')"
      class="w-[min(92vw,30rem)]"
      @update:visible="
        (value) => {
          if (!value && cancellingId === null) pendingCancellation = null
        }
      "
    >
      <p>{{ t('directPlay.cancelWarning', { code: pendingCancellation?.code ?? '' }) }}</p>
      <p v-if="pendingCancellation" class="mt-3 font-semibold">{{ pendingCancellation.code }}</p>
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
