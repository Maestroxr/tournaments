<script setup lang="ts">
import InputNumber from 'primevue/inputnumber'
import ToggleSwitch from 'primevue/toggleswitch'
import { useI18n } from '@/i18n'

withDefaults(defineProps<{
  showOpeningBalance?: boolean
  showActive?: boolean
  balanceError?: string
}>(), {
  showOpeningBalance: false,
  showActive: false,
  balanceError: '',
})

const isStaff = defineModel<boolean>('isStaff', { required: true })
const isActive = defineModel<boolean>('isActive', { default: true })
const openingBalance = defineModel<number | null>('openingBalance', { default: null })
const { direction, t } = useI18n()
</script>

<template>
  <section class="overflow-hidden rounded-xl border border-zinc-200 bg-white">
    <div class="border-b border-zinc-200 bg-zinc-50 px-5 py-4 sm:px-6">
      <div class="flex items-center gap-3">
        <span class="grid h-9 w-9 place-items-center rounded-lg bg-amber-400/15 text-amber-200">
          <i class="bi bi-shield-check" />
        </span>
        <div>
          <h2 class="text-lg font-semibold text-black">{{ showOpeningBalance ? t('users.setupOptions') : t('users.permissions') }}</h2>
          <p class="text-xs text-zinc-500">{{ showOpeningBalance ? t('users.setupOptionsHint') : t('users.permissionsHint') }}</p>
        </div>
      </div>
    </div>

    <div class="divide-y divide-zinc-200 px-5 sm:px-6">
      <div v-if="showOpeningBalance" class="grid gap-4 py-5 sm:grid-cols-[minmax(0,1fr)_190px] sm:items-center">
        <div class="flex items-start gap-3">
          <span class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-emerald-400/10 text-emerald-300"><i class="bi bi-wallet2" /></span>
          <div><label for="initial-balance" class="block text-sm font-semibold text-black">{{ t('users.initialBalance') }}</label><p class="mt-1 text-xs leading-5 text-zinc-500">{{ t('users.initialBalanceHint') }}</p></div>
        </div>
        <div>
          <InputNumber v-model="openingBalance" input-id="initial-balance" mode="currency" currency="USD" :locale="direction === 'rtl' ? 'he-IL' : 'en-US'" :min="0" :max="99999999.99" :min-fraction-digits="2" :max-fraction-digits="2" :placeholder="t('users.initialBalancePlaceholder')" fluid />
          <small v-if="balanceError" class="mt-1 block text-red-400">{{ balanceError }}</small>
        </div>
      </div>

      <label class="flex cursor-pointer items-center justify-between gap-4 py-5">
        <span class="flex items-start gap-3">
          <span class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-amber-400/10 text-amber-300"><i class="bi bi-shield-lock" /></span>
          <span><strong class="block text-sm text-black">{{ t('users.staffAccess') }}</strong><span class="mt-1 block text-xs leading-5 text-zinc-500">{{ t('users.staffAccessHint') }}</span></span>
        </span>
        <ToggleSwitch v-model="isStaff" />
      </label>

      <label v-if="showActive" class="flex cursor-pointer items-center justify-between gap-4 py-5">
        <span class="flex items-start gap-3">
          <span class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-emerald-400/10 text-emerald-300"><i class="bi bi-person-check" /></span>
          <span><strong class="block text-sm text-black">{{ t('users.activeAccount') }}</strong><span class="mt-1 block text-xs leading-5 text-zinc-500">{{ t('users.activeAccountHint') }}</span></span>
        </span>
        <ToggleSwitch v-model="isActive" />
      </label>
    </div>
  </section>
</template>
