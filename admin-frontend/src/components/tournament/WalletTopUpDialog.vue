<script setup lang="ts">
import { computed, ref } from 'vue'
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import InputNumber from 'primevue/inputnumber'
import InputText from 'primevue/inputtext'
import AppAlert from '@/components/AppAlert.vue'
import { apiFetch, ApiError, formatApiError } from '@/services/api'
import { useI18n } from '@/i18n'

const props = defineProps<{ user: { id: number; username: string; balance?: string | null }; entryFee: number }>()
const emit = defineEmits<{ close: []; saved: [balance: string] }>()
const { t, locale } = useI18n()
const parsedBalance = Number(props.user.balance ?? 0)
const currentBalanceCents = Number.isFinite(parsedBalance) ? Math.round(parsedBalance * 100) : 0
const requiredCents = Math.max(1, Math.round(props.entryFee * 100) - currentBalanceCents)
const minimumAmount = requiredCents / 100
const amount = ref<number | null>(minimumAmount)
const note = ref('')
const saving = ref(false)
const uncertain = ref(false)
const error = ref('')
const valid = computed(() => amount.value !== null && Number.isFinite(amount.value) && Math.round(amount.value * 100) >= requiredCents && amount.value <= 99999999.99)
function money(value: number) { return value.toLocaleString(locale.value === 'he' ? 'he-IL' : 'en-US', { maximumFractionDigits: 2 }) }
async function save() {
  if (!valid.value || saving.value || uncertain.value) return
  saving.value = true
  error.value = ''
  try {
    const data = await apiFetch<{ balance: string }>(`/api/admin/users/${props.user.id}/wallet`, {
      method: 'POST', body: JSON.stringify({ action: 'deposit', amount: amount.value, note: note.value.trim() }),
    })
    emit('saved', data.balance)
  } catch (caught: unknown) {
    uncertain.value = !(caught instanceof ApiError) || caught.status >= 500
    error.value = uncertain.value ? t('attendees.topUpUncertain') : formatApiError(caught)
  } finally { saving.value = false }
}
function close() { if (!saving.value) emit('close') }
</script>

<template>
  <Dialog :visible="true" modal append-to="self" :header="t('attendees.topUpFor', { name: user.username })" :closable="!saving" :close-on-escape="!saving" :style="{ width: '440px', maxWidth: 'calc(100vw - 32px)', background: '#111a2f', color: '#edf3ff', borderColor: '#31425f' }" @update:visible="close">
    <form class="space-y-4" @submit.prevent="save">
      <p class="text-sm text-zinc-500">{{ t('attendees.balance', { amount: money(Number(user.balance ?? 0)) }) }} · {{ t('attendees.entryFee', { amount: money(entryFee) }) }}</p>
      <p class="text-sm text-zinc-500">{{ t('attendees.topUpHint') }}</p>
      <AppAlert v-if="error" type="error" :message="error" />
      <label class="block"><span class="mb-2 block text-sm text-black">{{ t('common.amount') }}</span><InputNumber v-model="amount" :min="minimumAmount" :max="99999999.99" :max-fraction-digits="2" highlight-on-focus fluid :disabled="saving || uncertain" /></label>
      <label class="block"><span class="mb-2 block text-sm text-black">{{ t('common.note') }}</span><InputText v-model="note" class="w-full" :disabled="saving || uncertain" /></label>
      <p v-if="valid" class="text-sm text-emerald-700">{{ t('attendees.balanceAfter', { amount: money((Math.round(Number(user.balance ?? 0) * 100) + Math.round(Number(amount) * 100)) / 100) }) }}</p>
      <div class="flex justify-end gap-2">
        <Button type="button" :label="t('common.cancel')" severity="secondary" outlined :disabled="saving" @click="close" />
        <Button type="submit" :label="t('attendees.confirmTopUp')" severity="success" :loading="saving" :disabled="!valid || uncertain" />
      </div>
    </form>
  </Dialog>
</template>
