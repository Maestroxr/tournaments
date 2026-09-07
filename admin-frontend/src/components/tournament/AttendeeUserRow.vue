<script setup lang="ts">
import { computed } from 'vue'
import Button from 'primevue/button'
import UserQuickView from '@/components/UserQuickView.vue'
import { useI18n } from '@/i18n'

const props = defineProps<{
  user: { id: number; username: string; phone_number?: string; balance?: string | null }
  entryFee: number
  disabled?: boolean
  loading?: boolean
}>()
const emit = defineEmits<{ add: [id: number]; topUp: [] }>()
const { t, locale } = useI18n()
const balance = computed(() =>
  props.user.balance == null || !Number.isFinite(Number(props.user.balance))
    ? null
    : Number(props.user.balance),
)
const shortfall = computed(() =>
  balance.value === null
    ? null
    : Math.max(0, Math.round(props.entryFee * 100) - Math.round(balance.value * 100)) / 100,
)
const blocked = computed(
  () =>
    props.disabled ||
    props.loading ||
    (props.entryFee > 0 && (shortfall.value === null || shortfall.value > 0)),
)
function money(value: number) {
  return value.toLocaleString(locale.value === 'he' ? 'he-IL' : 'en-US', {
    maximumFractionDigits: 2,
  })
}
function add() {
  if (!blocked.value) emit('add', props.user.id)
}
</script>

<template>
  <article class="attendee-user-row">
    <div class="attendee-user-row__identity">
      <UserQuickView :user-id="user.id" :username="user.username" />
    </div>
    <div v-if="entryFee > 0" class="attendee-user-row__funding">
      <span class="attendee-user-row__balance">
        {{
          balance === null
            ? t('attendees.balanceUnavailable')
            : t('attendees.balance', { amount: money(balance) })
        }}
      </span>
      <span
        v-if="shortfall !== null && shortfall > 0"
        class="attendee-user-row__shortfall"
      >
        <i class="bi bi-exclamation-circle me-1" aria-hidden="true"></i
        >{{ t('attendees.shortfall', { amount: money(shortfall) }) }}
      </span>
      <span v-else-if="shortfall === 0" class="attendee-user-row__ready">
        {{ t('attendees.enoughBalance') }}
      </span>
    </div>
    <div class="attendee-user-row__actions">
      <Button
        v-if="entryFee > 0 && shortfall !== null && shortfall > 0"
        icon="bi bi-wallet2"
        :label="t('attendees.topUp')"
        :aria-label="t('attendees.topUpFor', { name: user.username })"
        :disabled="disabled || loading"
        size="small"
        severity="info"
        outlined
        @click="emit('topUp')"
      />
      <Button
        icon="bi bi-person-plus"
        :label="t('attendees.addUser')"
        :aria-label="t('attendees.addNamedUser', { name: user.username })"
        :title="entryFee > 0 && shortfall !== null && shortfall > 0 ? t('attendees.insufficientBalance') : undefined"
        :disabled="Boolean(blocked)"
        :loading="loading"
        size="small"
        severity="success"
        outlined
        @click="add"
      />
    </div>
  </article>
</template>

<style scoped>
.attendee-user-row {
  display: flex;
  align-items: center;
  gap: 14px 20px;
  min-height: 64px;
  padding: 10px 2px;
  border-bottom: 1px solid #263653;
}
.attendee-user-row:last-child {
  border-bottom: 0;
}
.attendee-user-row__identity {
  flex: 0 1 200px;
  min-width: 0;
  overflow-wrap: anywhere;
}
.attendee-user-row__identity :deep(.p-button) {
  max-width: 100%;
  padding-inline: 4px;
}
.attendee-user-row__funding {
  display: flex;
  align-items: center;
  flex: 1 1 260px;
  flex-wrap: wrap;
  gap: 5px 14px;
  min-width: 0;
  font-size: 12px;
}
.attendee-user-row__balance { color: #b7c7dd; }
.attendee-user-row__shortfall { color: #f5c35b; }
.attendee-user-row__ready { color: #63d6a6; }
.attendee-user-row__actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: nowrap;
  justify-content: flex-end;
  gap: 8px;
}
.attendee-user-row :deep(.p-button) {
  flex-shrink: 0;
}
@media (max-width: 760px) {
  .attendee-user-row { flex-wrap: wrap; }
  .attendee-user-row__identity { flex: 1 1 160px; }
  .attendee-user-row__funding { flex: 1 1 220px; }
  .attendee-user-row__actions { flex: 1 0 100%; }
}
@media (max-width: 480px) {
  .attendee-user-row__funding { flex-basis: 100%; }
  .attendee-user-row__actions :deep(.p-button) {
    flex: 1 1 auto;
  }
}
</style>
