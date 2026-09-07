<script setup lang="ts">
import Button from 'primevue/button'
import UserQuickView from '@/components/UserQuickView.vue'
import { useI18n } from '@/i18n'

export interface RosterAttendee {
  id: number
  name: string
  username?: string | null
  user_id: number | null
  status: 'registered' | 'waitlisted' | 'withdrawn' | 'disqualified'
  payment_status: 'paid' | 'unpaid' | 'waived' | 'refunded'
  refundable?: string
}

defineProps<{ attendee: RosterAttendee; removable?: boolean; loading?: boolean }>()
const emit = defineEmits<{ remove: [id: number] }>()
const { t } = useI18n()
</script>

<template>
  <article class="roster-row">
    <span class="roster-row__avatar" aria-hidden="true">{{ (attendee.name.trim()[0] || '?').toUpperCase() }}</span>
    <UserQuickView :user-id="attendee.user_id" :username="attendee.username || attendee.name" />
    <Button
      v-if="removable"
      icon="bi bi-person-x"
      :label="t('attendees.remove')"
      :aria-label="t('attendees.removeNamed', { name: attendee.name })"
      severity="danger"
      outlined
      size="small"
      :loading="loading"
      :disabled="loading"
      @click="emit('remove', attendee.id)"
    />
  </article>
</template>

<style scoped>
.roster-row { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 12px; min-height: 68px; padding: 12px 14px; border: 1px solid #2b3c59; border-radius: 11px; background: #121d32; }
.roster-row__avatar { display: grid; width: 40px; height: 40px; place-items: center; border-radius: 11px; background: #253a5b; color: #b9dcff; font-weight: 800; }
@media (max-width: 480px) { .roster-row { grid-template-columns: auto minmax(0, 1fr); } .roster-row :deep(.p-button) { grid-column: 1 / -1; width: 100%; } }
</style>
