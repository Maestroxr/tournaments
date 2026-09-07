<script setup lang="ts">
import { computed } from 'vue'
import Button from 'primevue/button'
import { useI18n } from '@/i18n'

const props = withDefaults(defineProps<{
  to?: string
  eyebrow?: string
  title?: string
  description?: string
  actionLabel?: string
  icon?: string
}>(), {
  to: '/tournaments/new',
  icon: 'bi bi-trophy',
})
const { t } = useI18n()
const eyebrowText = computed(() => props.eyebrow || t('tournamentBanner.eyebrow'))
const titleText = computed(() => props.title || t('tournamentBanner.title'))
const descriptionText = computed(() => props.description || t('tournamentBanner.description'))
const actionText = computed(() => props.actionLabel || t('tournamentBanner.action'))
</script>

<template>
  <section class="create-tournament-banner" :aria-label="titleText">
    <div class="create-tournament-banner__copy">
      <p class="create-tournament-banner__eyebrow">{{ eyebrowText }}</p>
      <h2 class="create-tournament-banner__title" dir="auto">{{ titleText }}</h2>
      <p class="create-tournament-banner__description">{{ descriptionText }}</p>
    </div>
    <Button
      as="router-link"
      :to="to"
      :label="actionText"
      :icon="icon"
      rounded
      class="create-tournament-banner__button"
    />
  </section>
</template>

<style scoped>
.create-tournament-banner {
  position: relative;
  isolation: isolate;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  overflow: hidden;
  padding: 17px 22px;
  border: 1px solid #2879ef;
  border-radius: 16px;
  background: linear-gradient(115deg, #075cf2 0%, #075dcc 65%, #0854aa 100%);
  color: #fff;
  box-shadow: 0 4px 14px rgb(4 79 181 / 10%);
}

.create-tournament-banner::after {
  position: absolute;
  z-index: -1;
  inset-inline-end: -34px;
  top: -64px;
  width: 190px;
  height: 190px;
  border-radius: 50%;
  background: rgb(255 255 255 / 8%);
  content: '';
  pointer-events: none;
}

.create-tournament-banner__copy { min-width: 0; }
.create-tournament-banner__eyebrow {
  margin: 0 0 4px;
  color: #dbeafe;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.create-tournament-banner__title {
  margin: 0;
  color: #fff;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.35;
}
.create-tournament-banner__description {
  margin: 3px 0 0;
  color: #e6efff;
  font-size: 13px;
  line-height: 1.6;
}
.create-tournament-banner .create-tournament-banner__button {
  flex-shrink: 0;
  min-height: 38px;
  padding: 8px 17px;
  border: 1px solid #fff;
  border-radius: 999px;
  background: #fff;
  color: #075bbb;
  font-size: 13px;
  font-weight: 700;
  box-shadow: none;
  text-decoration: none;
}
.create-tournament-banner .create-tournament-banner__button:hover {
  border-color: #dbeafe;
  background: #eff6ff;
  color: #034693;
}
.create-tournament-banner .create-tournament-banner__button:focus-visible {
  outline: 3px solid #fff;
  outline-offset: 4px;
}
@media (max-width: 540px) {
  .create-tournament-banner {
    align-items: stretch;
    flex-direction: column;
    gap: 11px;
    padding: 16px;
  }
  .create-tournament-banner__button { align-self: flex-start; }
}
</style>
