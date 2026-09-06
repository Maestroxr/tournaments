<script setup lang="ts">
import Button from 'primevue/button'
import { useI18n } from '@/i18n'

const { t } = useI18n()
</script>

<template>
  <section class="mx-auto flex min-h-[55vh] max-w-xl flex-col items-center justify-center px-4 text-center">
    <div class="text-sm font-semibold text-amber-600">404</div>
    <h1 class="mt-2 text-2xl font-bold text-black">{{ t('common.pageNotFound') }}</h1>
    <p class="mt-2 text-sm text-zinc-500">{{ t('common.pageMissing') }}</p>
    <div class="mt-6 flex flex-wrap justify-center gap-2">
      <Button as="router-link" to="/dashboard" :label="t('common.backDashboard')" severity="contrast" />
      <Button as="router-link" to="/tournaments" :label="t('common.backTournaments')" severity="secondary" outlined />
    </div>
  </section>
</template>
