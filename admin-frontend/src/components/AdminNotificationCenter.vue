<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import Badge from 'primevue/badge'
import Button from 'primevue/button'
import Popover from 'primevue/popover'
import Toast from 'primevue/toast'
import { useToast } from 'primevue/usetoast'
import { useI18n } from '@/i18n'
import {
  ADMIN_NOTIFICATIONS_CHANGED_EVENT,
  apiFetch,
  formatApiError,
} from '@/services/api'
import type {
  AdminNotification,
  AdminNotificationsPayload,
} from '@/types/notifications'

const { t, locale } = useI18n()
const toast = useToast()
const popover = ref<InstanceType<typeof Popover> | null>(null)
const triggerContainer = ref<HTMLElement | null>(null)
const notifications = ref<AdminNotification[]>([])
const loading = ref(false)
const error = ref('')
const expanded = ref(false)
let refreshQueued = false
let queuedAnnouncement = false
let refreshTimer: ReturnType<typeof setInterval> | null = null
let initialized = false
let disposed = false
let knownNotificationIds = new Set<string>()

const count = computed(() => notifications.value.length)
const badgeValue = computed(() => count.value > 99 ? '99+' : String(count.value))
const triggerLabel = computed(() => count.value
  ? t('notifications.openWithCount', { count: count.value })
  : t('notifications.open'))

function toastSeverity(item: AdminNotification) {
  if (item.kind === 'ready_to_start') return 'success'
  if (item.severity === 'critical') return 'error'
  if (item.severity === 'warning') return 'warn'
  return 'info'
}

function announceNewNotifications(items: AdminNotification[]) {
  const added = items.filter(item => !knownNotificationIds.has(item.notification_id))
  if (!initialized || !added.length) return
  if (added.length === 1) {
    const item = added[0]!
    toast.add({
      group: 'admin-notifications',
      severity: toastSeverity(item),
      summary: t('notifications.newTitle', {
        type: t(`dashboard.attentionKinds.${item.kind}`),
      }),
      detail: `${item.name} · ${notificationMessage(item)}`,
      life: 7000,
    })
    return
  }
  toast.add({
    group: 'admin-notifications',
    severity: 'info',
    summary: t('notifications.multipleNew', { count: added.length }),
    detail: t('notifications.multipleNewHint'),
    life: 7000,
  })
}

async function load(announceNew = false) {
  if (disposed) return
  if (loading.value) {
    refreshQueued = true
    queuedAnnouncement ||= announceNew
    return
  }
  loading.value = true
  error.value = ''
  try {
    const payload = await apiFetch<AdminNotificationsPayload>('/api/admin/notifications')
    if (disposed) return
    const nextNotifications = Array.isArray(payload.notifications) ? payload.notifications : []
    if (announceNew || queuedAnnouncement) announceNewNotifications(nextNotifications)
    notifications.value = nextNotifications
    knownNotificationIds = new Set(nextNotifications.map(item => item.notification_id))
    initialized = true
  } catch (caught: unknown) {
    if (!disposed) error.value = formatApiError(caught)
  } finally {
    if (disposed) {
      refreshQueued = false
      queuedAnnouncement = false
      return
    }
    loading.value = false
    if (refreshQueued) {
      const announceQueued = queuedAnnouncement
      refreshQueued = false
      queuedAnnouncement = false
      void load(announceQueued)
    }
  }
}

function toggle(event: Event) {
  const opening = !expanded.value
  expanded.value = opening
  popover.value?.toggle(event)
  if (opening) void load()
}

function close(restoreFocus = false) {
  popover.value?.hide()
  expanded.value = false
  if (restoreFocus) void nextTick(() => triggerContainer.value?.querySelector('button')?.focus())
}

function notificationMessage(item: AdminNotification) {
  if (item.kind === 'overdue') return t('dashboard.attentionMessages.overdue')
  if (item.kind === 'ready_to_start') {
    return t('dashboard.attentionMessages.readyToStart', { count: item.participant_count })
  }
  if (item.kind === 'waiting_players') {
    const missing = Math.max(item.min_players - item.participant_count, 0)
    return t(
      missing === 1
        ? 'dashboard.attentionMessages.waitingPlayersOne'
        : 'dashboard.attentionMessages.waitingPlayersMany',
      { count: missing },
    )
  }
  if (item.kind === 'pending_matches') {
    const pending = item.pending_matches ?? 0
    return t(
      pending === 1
        ? 'dashboard.attentionMessages.pendingMatchesOne'
        : 'dashboard.attentionMessages.pendingMatchesMany',
      { count: pending },
    )
  }
  return t('dashboard.attentionMessages.draft')
}

function actionLabel(kind: AdminNotification['kind']) {
  if (kind === 'overdue') return t('dashboard.actions.reviewTournament')
  if (kind === 'ready_to_start') return t('dashboard.actions.startTournament')
  if (kind === 'waiting_players') return t('dashboard.actions.managePlayers')
  if (kind === 'pending_matches') return t('dashboard.primary.openControlRoom')
  return t('dashboard.actions.continueEditing')
}

function severityIcon(item: AdminNotification) {
  if (item.kind === 'ready_to_start') return 'bi bi-play-fill'
  if (item.severity === 'critical') return 'bi bi-exclamation-lg'
  if (item.severity === 'warning') return 'bi bi-exclamation-triangle'
  return 'bi bi-info-lg'
}

function handleRefreshEvent() {
  void load(true)
}

onMounted(() => {
  disposed = false
  void load()
  window.addEventListener(ADMIN_NOTIFICATIONS_CHANGED_EVENT, handleRefreshEvent)
  refreshTimer = setInterval(() => void load(true), 30_000)
})

onBeforeUnmount(() => {
  disposed = true
  refreshQueued = false
  queuedAnnouncement = false
  window.removeEventListener(ADMIN_NOTIFICATIONS_CHANGED_EVENT, handleRefreshEvent)
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<template>
  <Toast
    group="admin-notifications"
    :position="locale === 'he' ? 'top-left' : 'top-right'"
  />
  <div ref="triggerContainer" class="admin-notifications-trigger">
    <Button
      icon="bi bi-bell"
      text
      rounded
      severity="secondary"
      :aria-label="triggerLabel"
      aria-haspopup="dialog"
      aria-controls="admin-notifications-panel"
      :aria-expanded="expanded"
      @click="toggle"
    />
    <Badge
      v-if="count"
      class="admin-notifications-trigger__badge"
      severity="danger"
      :value="badgeValue"
      aria-hidden="true"
    />
    <span class="sr-only" aria-live="polite">
      {{ t('notifications.activeCount', { count }) }}
    </span>
  </div>

  <Popover
    ref="popover"
    unstyled
    append-to="body"
    :base-z-index="1200"
    @show="expanded = true"
    @hide="expanded = false"
  >
    <section
      id="admin-notifications-panel"
      class="admin-notifications-panel"
      role="dialog"
      aria-modal="false"
      aria-labelledby="admin-notifications-title"
    >
      <header class="admin-notifications-panel__header">
        <div>
          <p>{{ t('notifications.eyebrow') }}</p>
          <h2 id="admin-notifications-title">{{ t('notifications.title') }}</h2>
        </div>
        <div class="admin-notifications-panel__header-actions">
          <span v-if="count">{{ t('notifications.activeCount', { count }) }}</span>
          <Button
            icon="bi bi-arrow-clockwise"
            text
            rounded
            size="small"
            :loading="loading"
            :aria-label="t('notifications.refresh')"
            @click="load()"
          />
          <Button
            icon="bi bi-x-lg"
            text
            rounded
            size="small"
            :aria-label="t('common.close')"
            @click="close(true)"
          />
        </div>
      </header>

      <div v-if="loading && !notifications.length" class="admin-notifications-panel__state" role="status">
        <i class="bi bi-arrow-repeat admin-notifications-panel__spin" aria-hidden="true"></i>
        <span>{{ t('notifications.loading') }}</span>
      </div>
      <div v-else-if="error && !notifications.length" class="admin-notifications-panel__state admin-notifications-panel__state--error" role="alert">
        <i class="bi bi-exclamation-circle" aria-hidden="true"></i>
        <strong>{{ t('notifications.loadFailed') }}</strong>
        <span>{{ error }}</span>
        <Button :label="t('common.retry')" size="small" severity="secondary" outlined @click="load()" />
      </div>
      <div v-else-if="!notifications.length" class="admin-notifications-panel__state">
        <i class="bi bi-check-circle-fill admin-notifications-panel__clear" aria-hidden="true"></i>
        <strong>{{ t('notifications.emptyTitle') }}</strong>
        <span>{{ t('notifications.emptyHint') }}</span>
      </div>
      <div v-else class="admin-notifications-panel__list">
        <RouterLink
          v-for="item in notifications"
          :key="item.notification_id"
          :to="item.action_to"
          class="admin-notification-item"
          :class="[`admin-notification-item--${item.severity}`, { 'admin-notification-item--ready': item.kind === 'ready_to_start' }]"
          @click="close()"
        >
          <span class="admin-notification-item__icon" aria-hidden="true"><i :class="severityIcon(item)"></i></span>
          <span class="admin-notification-item__copy">
            <span class="admin-notification-item__topline">
              <strong dir="auto">{{ item.name }}</strong>
              <small>{{ t(`dashboard.attentionKinds.${item.kind}`) }}</small>
            </span>
            <span>{{ notificationMessage(item) }}</span>
            <b>{{ actionLabel(item.kind) }} <i class="bi bi-chevron-right rtl:rotate-180" aria-hidden="true"></i></b>
          </span>
        </RouterLink>
      </div>

      <footer class="admin-notifications-panel__footer">
        <RouterLink to="/dashboard#attention-heading" @click="close()">
          {{ t('notifications.openDashboard') }}
        </RouterLink>
      </footer>
    </section>
  </Popover>
</template>

<style scoped>
.admin-notifications-trigger { position: relative; display: inline-flex; }
.admin-notifications-trigger :deep(.p-button) { color: #c8d6ee; }
.admin-notifications-trigger :deep(.p-button:hover) { background: rgb(116 158 225 / 14%); color: #fff; }
.admin-notifications-trigger__badge {
  position: absolute;
  inset-block-start: -4px;
  inset-inline-end: -5px;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  border: 2px solid #11182d;
  font-size: 9px;
  pointer-events: none;
}
.admin-notifications-panel {
  display: grid;
  width: min(400px, calc(100vw - 24px));
  max-height: min(620px, calc(100vh - 90px));
  overflow: hidden;
  border: 1px solid #30415f;
  border-radius: 14px;
  background: #10192d;
  box-shadow: 0 22px 60px rgb(0 0 0 / 48%);
  color: #e9f0fc;
  text-align: start;
}
.admin-notifications-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid #293955;
}
.admin-notifications-panel__header p { margin: 0 0 3px; color: #7990b2; font-size: 9px; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; }
.admin-notifications-panel__header h2 { margin: 0; color: #f5f8ff; font-size: 17px; font-weight: 700; }
.admin-notifications-panel__header-actions { display: flex; align-items: center; gap: 3px; }
.admin-notifications-panel__header-actions > span { margin-inline-end: 5px; color: #92a6c4; font-size: 10px; white-space: nowrap; }
.admin-notifications-panel__header-actions :deep(.p-button) { width: 30px; height: 30px; color: #aabbd5; }
.admin-notifications-panel__list { overflow-y: auto; overscroll-behavior: contain; }
.admin-notification-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 11px;
  padding: 13px 15px;
  border-bottom: 1px solid #24334e;
  color: inherit;
  text-decoration: none;
  transition: background 140ms ease;
}
.admin-notification-item:hover { background: #182641; }
.admin-notification-item:focus-visible { outline: 2px solid #74b8ff; outline-offset: -3px; }
.admin-notification-item__icon { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 9px; background: #253956; color: #9cc9ff; }
.admin-notification-item--warning .admin-notification-item__icon { background: #493b20; color: #f0cc6b; }
.admin-notification-item--critical .admin-notification-item__icon { background: #512c2d; color: #ffaaa7; }
.admin-notification-item--ready .admin-notification-item__icon { background: #176b59; color: #d3fff2; }
.admin-notification-item__copy { display: grid; min-width: 0; gap: 4px; color: #aebdd4; font-size: 11px; line-height: 1.45; }
.admin-notification-item__topline { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.admin-notification-item__topline strong { overflow: hidden; color: #f0f5ff; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.admin-notification-item__topline small { flex: 0 0 auto; border-radius: 999px; padding: 2px 7px; background: #21324e; color: #aac3e8; font-size: 9px; }
.admin-notification-item__copy b { margin-top: 2px; color: #83c6ff; font-size: 10px; font-weight: 700; }
.admin-notification-item--ready .admin-notification-item__copy b { color: #83e1c5; }
.admin-notifications-panel__state { display: grid; min-height: 210px; place-items: center; align-content: center; gap: 8px; padding: 24px; color: #9dafc9; text-align: center; font-size: 11px; }
.admin-notifications-panel__state > i { font-size: 24px; }
.admin-notifications-panel__state strong { color: #e9effa; font-size: 13px; }
.admin-notifications-panel__state--error > i { color: #f099a4; }
.admin-notifications-panel__clear { color: #5fd3ac; }
.admin-notifications-panel__spin { animation: admin-notifications-spin 850ms linear infinite; }
.admin-notifications-panel__footer { padding: 10px 15px; border-top: 1px solid #293955; text-align: center; }
.admin-notifications-panel__footer a { color: #8fcaff; font-size: 11px; font-weight: 650; text-decoration: none; }
.admin-notifications-panel__footer a:hover { text-decoration: underline; }
@keyframes admin-notifications-spin { to { transform: rotate(360deg); } }
@media (max-width: 520px) {
  .admin-notifications-panel { max-height: calc(100dvh - 76px); }
}
</style>
