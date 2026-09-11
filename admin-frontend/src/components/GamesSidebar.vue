<script setup lang="ts">
import { computed } from 'vue'
import Menu from 'primevue/menu'
import { useI18n } from '@/i18n'

type GamesSection = 'monitor' | 'formats' | 'match' | 'friend' | 'quick' | 'settings'
defineProps<{ modelValue: GamesSection }>()
const emit = defineEmits<{ 'update:modelValue': [value: GamesSection] }>()
const { t, locale } = useI18n()
const items = computed(() => [
  {
    label: t('directPlay.navigation.monitor'),
    icon: 'bi bi-controller',
    value: 'monitor' as const,
  },
  { label: locale.value === 'he' ? 'פורמטים וחוקים' : 'Formats and rules', icon: 'bi bi-dice-5', value: 'formats' as const },
  { label: t('directPlay.modes.match') + ' (Legacy)', icon: 'bi bi-dice-5', value: 'match' as const },
  { label: t('directPlay.modes.friend') + ' (Legacy)', icon: 'bi bi-people', value: 'friend' as const },
  { label: t('directPlay.modes.quick') + ' (Legacy)', icon: 'bi bi-lightning-charge', value: 'quick' as const },
  { label: t('directPlay.sharedSettingsTitle'), icon: 'bi bi-sliders', value: 'settings' as const },
])
</script>

<template>
  <nav class="games-sidebar" :aria-label="t('directPlay.navigation.title')">
    <p>{{ t('directPlay.navigation.title') }}</p>
    <Menu :model="items" unstyled>
      <template #item="{ item }">
        <button
          type="button"
          class="games-sidebar__link"
          :class="{ 'is-selected': modelValue === item.value }"
          :aria-current="modelValue === item.value ? 'page' : undefined"
          :aria-controls="`games-${item.value}`"
          @click="emit('update:modelValue', item.value)"
        >
          <i :class="item.icon" aria-hidden="true" />
          <span>{{ item.label }}</span>
        </button>
      </template>
    </Menu>
  </nav>
</template>

<style scoped>
.games-sidebar {
  position: sticky;
  top: 20px;
  align-self: start;
  min-width: 0;
  padding: 16px;
  border: 1px solid #263653;
  border-radius: 12px;
  background: #101a2e;
}
.games-sidebar > p {
  margin: 0 10px 12px;
  color: #dbe7f8;
  font-size: 14px;
  font-weight: 700;
}
.games-sidebar :deep(.p-menu-list) {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.games-sidebar__link {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 44px;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: #b9c9e1;
  font-size: 14px;
  font-weight: 650;
  text-align: start;
  cursor: pointer;
}
.games-sidebar__link:hover {
  background: #17253c;
  color: #edf5ff;
}
.games-sidebar__link:focus-visible {
  outline: 2px solid #62c7ef;
  outline-offset: 2px;
}
.games-sidebar__link.is-selected {
  border-color: #2a7094;
  background: #123b55;
  color: #85ddff;
}
@media (max-width: 820px) {
  .games-sidebar {
    position: static;
  }
  .games-sidebar > p {
    display: none;
  }
  .games-sidebar :deep(.p-menu-list) {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
