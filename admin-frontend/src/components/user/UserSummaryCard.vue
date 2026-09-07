<script setup lang="ts">
import { useI18n } from '@/i18n'

withDefaults(defineProps<{
  username: string
  phoneNumber: string
  isStaff: boolean
  isActive?: boolean
  balance?: number | string | null
  balanceType?: 'opening' | 'current'
  showStatus?: boolean
}>(), {
  isActive: true,
  balance: 0,
  balanceType: 'current',
  showStatus: false,
})

const { t } = useI18n()
</script>

<template>
  <section class="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm">
    <div class="border-b border-zinc-200 bg-zinc-50 p-5">
      <p class="text-xs font-semibold uppercase tracking-wider text-sky-300">{{ showStatus ? t('users.profileSummary') : t('users.preview') }}</p>
      <div class="mt-3 flex items-center gap-3">
        <span class="grid h-12 w-12 place-items-center rounded-full bg-sky-400/15 text-xl font-bold text-sky-200">{{ (username.trim()[0] || '?').toUpperCase() }}</span>
        <div class="min-w-0"><h2 class="truncate text-xl font-semibold text-black">{{ username || t('users.newUser') }}</h2><p class="truncate text-xs text-zinc-500">{{ phoneNumber || t('common.noPhone') }}</p></div>
      </div>
    </div>
    <div class="space-y-3 p-5">
      <div class="flex items-center justify-between rounded-lg bg-zinc-50 px-3 py-2.5 text-sm"><span class="text-zinc-500">{{ t('users.role') }}</span><span :class="['rounded-full px-2 py-1 text-xs font-semibold', isStaff ? 'bg-amber-400/15 text-amber-200' : 'bg-emerald-400/15 text-emerald-200']">{{ isStaff ? t('common.staff') : t('common.user') }}</span></div>
      <div v-if="showStatus" class="flex items-center justify-between rounded-lg bg-zinc-50 px-3 py-2.5 text-sm"><span class="text-zinc-500">{{ t('users.accountStatus') }}</span><span :class="['rounded-full px-2 py-1 text-xs font-semibold', isActive ? 'bg-emerald-400/15 text-emerald-200' : 'bg-red-400/15 text-red-300']">{{ isActive ? t('common.active') : t('common.inactive') }}</span></div>
      <div class="flex items-center justify-between rounded-lg bg-zinc-50 px-3 py-2.5 text-sm"><span class="text-zinc-500">{{ balanceType === 'opening' ? t('users.initialBalance') : t('users.currentBalance') }}</span><span class="font-semibold text-emerald-700">${{ Number(balance || 0).toFixed(2) }}</span></div>
      <slot />
      <div v-if="$slots.actions" class="grid gap-2 pt-2"><slot name="actions" /></div>
    </div>
  </section>
</template>
