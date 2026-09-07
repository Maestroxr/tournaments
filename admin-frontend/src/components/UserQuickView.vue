<script setup lang="ts">
import { ref } from 'vue'
import Button from 'primevue/button'
import Popover from 'primevue/popover'
import { apiFetch, formatApiError } from '@/services/api'
import type { AdminUserSummary } from '@/types/user'
import { useI18n } from '@/i18n'

const props = defineProps<{
  userId: number | null
  username: string
}>()

const loading = ref(false)
const error = ref('')
const user = ref<AdminUserSummary | null>(null)
const popover = ref<InstanceType<typeof Popover> | null>(null)
const { direction, t } = useI18n()

let closeTimer: ReturnType<typeof setTimeout> | null = null

function cancelClose() {
  if (!closeTimer) return
  clearTimeout(closeTimer)
  closeTimer = null
}

async function show(event: Event) {
  if (props.userId === null) return
  cancelClose()
  popover.value?.show(event)
  if (user.value || loading.value) return
  loading.value = true
  error.value = ''
  try {
    user.value = await apiFetch<AdminUserSummary>(`/api/admin/users/${props.userId}`)
  } catch (caught: unknown) {
    error.value = formatApiError(caught)
  } finally {
    loading.value = false
  }
}

function scheduleClose() {
  if (closeTimer) clearTimeout(closeTimer)
  closeTimer = setTimeout(() => {
    popover.value?.hide()
    closeTimer = null
  }, 150)
}

function close() {
  cancelClose()
  popover.value?.hide()
}
</script>

<template>
  <span class="inline-flex">
    <Button
      v-if="userId !== null"
      :label="username"
      icon="bi bi-person-circle"
      link
      severity="contrast"
      @mouseenter="show"
      @mouseleave="scheduleClose"
    />
    <span v-else class="inline-flex items-center gap-1 font-medium text-zinc-700">
      <i class="bi bi-person text-zinc-400" aria-hidden="true"></i>
      {{ username }}
    </span>

    <Popover
      ref="popover"
      dir="ltr"
      unstyled
      append-to="body"
      :base-z-index="1000"
    >
      <div
        class="user-quick-view"
        :dir="direction"
        @mouseenter="cancelClose"
        @mouseleave="scheduleClose"
        @focusin="cancelClose"
        @focusout="scheduleClose"
        @click.stop
      >
        <p v-if="loading" class="user-quick-view__message">{{ t('users.loadingUser') }}</p>
        <p v-else-if="error" class="user-quick-view__message user-quick-view__message--error">
          {{ error }}
        </p>
        <div v-else-if="user" class="user-quick-view__content">
          <header class="user-quick-view__header">
            <div class="user-quick-view__identity">
              <strong><bdi>{{ user.username }}</bdi></strong>
              <small>{{ t('users.userNumber', { id: user.id }) }}</small>
            </div>
            <button
              type="button"
              class="user-quick-view__close"
              :aria-label="t('users.closeDetails')"
              @click="close"
            >
              <i class="bi bi-x" aria-hidden="true"></i>
            </button>
          </header>

          <dl class="user-quick-view__details">
            <div>
              <dt>{{ t('users.phoneLabel') }}</dt>
              <dd dir="auto">{{ user.phone_number || t('common.noPhone') }}</dd>
            </div>
            <div>
              <dt>{{ t('users.roleLabel') }}</dt>
              <dd>{{ user.is_staff ? t('common.staff') : t('common.user') }}</dd>
            </div>
            <div>
              <dt>{{ t('users.statusLabel') }}</dt>
              <dd>{{ user.is_active ? t('common.active') : t('common.inactive') }}</dd>
            </div>
          </dl>

          <RouterLink :to="`/users/${user.id}/edit`" class="user-quick-view__edit">
            <i class="bi bi-pencil-square" aria-hidden="true"></i>
            <span>{{ t('users.editUser') }}</span>
          </RouterLink>
        </div>
      </div>
    </Popover>
  </span>
</template>

<style scoped>
.user-quick-view {
  width: min(280px, calc(100vw - 32px));
  padding: 16px;
  border: 1px solid #31425f;
  border-radius: 12px;
  background: #111a30;
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.38);
  color: #dce6f7;
  text-align: start;
}
.user-quick-view__message {
  margin: 0;
  color: #aab8d4;
  font-size: 13px;
}
.user-quick-view__message--error { color: #f39aaa; }
.user-quick-view__content { display: grid; gap: 14px; }
.user-quick-view__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.user-quick-view__identity { min-width: 0; }
.user-quick-view__identity strong,
.user-quick-view__identity small { display: block; }
.user-quick-view__identity strong {
  overflow-wrap: anywhere;
  color: #f4f7ff;
  font-size: 16px;
  line-height: 1.3;
}
.user-quick-view__identity small { margin-top: 2px; color: #899bb8; font-size: 11px; }
.user-quick-view__close {
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  padding: 0;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: #98a9c4;
  cursor: pointer;
  place-items: center;
}
.user-quick-view__close:hover { background: #1d2a43; color: #f4f7ff; }
.user-quick-view__close:focus-visible,
.user-quick-view__edit:focus-visible { outline: 2px solid #80dbff; outline-offset: 2px; }
.user-quick-view__details {
  display: grid;
  gap: 7px;
  margin: 0;
  font-size: 12px;
}
.user-quick-view__details div { display: flex; align-items: baseline; gap: 6px; }
.user-quick-view__details dt { color: #dce6f7; font-weight: 700; }
.user-quick-view__details dd { min-width: 0; margin: 0; color: #aab8d4; overflow-wrap: anywhere; }
.user-quick-view__edit {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 38px;
  border: 1px solid #397bc6;
  border-radius: 7px;
  background: #245f9e;
  color: #f7fbff;
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
}
.user-quick-view__edit:hover { border-color: #5d9ee8; background: #2c70b8; color: #fff; }
</style>
