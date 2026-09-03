<template>
  <button type="button" class="rounded border border-zinc-200 px-2.5 py-1 text-xs font-semibold text-zinc-700 hover:bg-zinc-50" :aria-label="t('common.language')" @click="toggleLocale">
    {{ locale === 'he' ? t('common.english') : t('common.hebrew') }}
  </button>
</template>

<script setup lang="ts">
import { useI18n } from '@/i18n'

const { locale, t, toggleLocale } = useI18n()
</script>
