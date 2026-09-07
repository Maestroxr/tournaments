<script setup lang="ts">
import { computed } from 'vue'
import Button from 'primevue/button'
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
  <div class="attendee-user-row">
    <span class="attendee-user-row__avatar" aria-hidden="true"><i class="bi bi-person"></i></span>
    <div class="attendee-user-row__identity">
      <p class="font-semibold text-black">{{ user.username }}</p>
      <p v-if="user.phone_number" class="text-xs text-zinc-500">{{ user.phone_number }}</p>
      <p class="mt-1 text-xs text-zinc-500">
        {{
          balance === null
            ? t('attendees.balanceUnavailable')
            : t('attendees.balance', { amount: money(balance) })
        }}
      </p>
      <p
        v-if="entryFee > 0 && shortfall !== null && shortfall > 0"
        class="mt-1 text-xs text-amber-700"
      >
        <i class="bi bi-exclamation-circle me-1" aria-hidden="true"></i
        >{{ t('attendees.shortfall', { amount: money(shortfall) }) }}
      </p>
      <p v-else-if="entryFee > 0 && shortfall === 0" class="mt-1 text-xs text-emerald-700">
        {{ t('attendees.enoughBalance') }}
      </p>
    </div>
    <div class="attendee-user-row__actions">
      <Button
        v-if="entryFee > 0 && shortfall !== null && shortfall > 0"
        icon="bi bi-wallet2"
        :label="t('attendees.topUp')"
        :disabled="disabled || loading"
        size="small"
        severity="info"
        outlined
        @click="emit('topUp')"
      />
      <Button
        icon="bi bi-person-plus"
        :label="
          entryFee > 0 && shortfall !== null && shortfall > 0
            ? t('attendees.insufficientBalance')
            : t('attendees.addUser')
        "
        :aria-label="t('attendees.addNamedUser', { name: user.username })"
        :disabled="Boolean(blocked)"
        :loading="loading"
        size="small"
        severity="secondary"
        outlined
        @click="add"
      />
    </div>
  </div>
</template>

<style scoped>
.attendee-user-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 10px 12px;
  padding: 16px 2px;
  border-bottom: 1px solid #263653;
}
.attendee-user-row:last-child {
  border-bottom: 0;
}
.attendee-user-row__avatar {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border: 1px solid rgba(111, 195, 255, 0.18);
  border-radius: 11px;
  background: #1a3150;
  color: #9bcfff;
}
.attendee-user-row__identity {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}
.attendee-user-row__identity > p:first-child {
  font-size: 13px;
}
.attendee-user-row__actions {
  display: flex;
  grid-column: 2;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}
.attendee-user-row :deep(.p-button) {
  flex-shrink: 0;
}
@media (max-width: 480px) {
  .attendee-user-row__actions {
    grid-column: 1 / -1;
  }
  .attendee-user-row__actions :deep(.p-button) {
    flex: 1 1 auto;
  }
}
</style>
