<script setup lang="ts">
import Button from 'primevue/button'

withDefaults(defineProps<{
  label: string
  description: string
  icon: string
  to?: string
  disabled?: boolean
  loading?: boolean
  tone?: 'neutral' | 'green'
}>(), { tone: 'neutral' })
defineEmits<{ activate: [] }>()
</script>

<template>
  <Button
    :as="to && !disabled ? 'router-link' : 'button'"
    :to="to && !disabled ? to : undefined"
    type="button"
    :disabled="disabled || loading"
    :aria-busy="loading"
    class="tournament-action"
    :class="{ 'tournament-action--green': tone === 'green' }"
    @click="$emit('activate')"
  >
    <span class="tournament-action__icon"><i :class="loading ? 'bi bi-arrow-repeat animate-spin' : icon" aria-hidden="true"></i></span>
    <span class="tournament-action__copy">
      <span class="tournament-action__label">{{ label }}</span>
      <span class="tournament-action__description">{{ description }}</span>
    </span>
    <i class="bi" :class="disabled ? 'bi-lock' : 'bi-chevron-right rtl:rotate-180'" aria-hidden="true"></i>
  </Button>
</template>

<style scoped>
.tournament-action.p-button {
  display: flex;
  width: 100%;
  justify-content: flex-start;
  gap: 14px;
  padding: 16px;
  border: 1px solid #2a3b57;
  border-radius: 12px;
  background: #15213a;
  color: #edf3ff;
  text-align: start;
  text-decoration: none;
}
.tournament-action.p-button:enabled:hover { border-color: #5a9fea; background: #1b2c49; }
.tournament-action.p-button:focus-visible { outline: 2px solid #6acfff; outline-offset: 3px; }
.tournament-action.p-button:disabled { opacity: 0.55; }
.tournament-action__icon {
  display: grid;
  flex: 0 0 38px;
  height: 38px;
  place-items: center;
  border-radius: 10px;
  background: #213453;
  color: #9acbff;
}
.tournament-action__copy { display: grid; flex: 1; min-width: 0; gap: 4px; }
.tournament-action__label { font-size: 14px; font-weight: 650; }
.tournament-action__description { color: #b0bfd6; font-size: 12px; font-weight: 400; line-height: 1.5; }
.tournament-action--green.p-button { background: #11745d; border-color: #208c72; }
.tournament-action--green.p-button:enabled:hover { background: #16856b; border-color: #5cddba; }
.tournament-action--green .tournament-action__icon { background: rgb(255 255 255 / 12%); color: #d0ffef; }
.tournament-action--green .tournament-action__description { color: #d0f3e9; }
</style>
