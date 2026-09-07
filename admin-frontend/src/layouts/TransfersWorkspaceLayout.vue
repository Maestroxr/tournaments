<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import Menu from 'primevue/menu'
import { useI18n } from '@/i18n'

const route = useRoute()
const { t } = useI18n()

const items = computed(() => [
  { label: t('transfers.navigation.transactions'), icon: 'bi bi-arrow-left-right', to: '/transfers', routeName: 'transfers' },
  { label: t('transfers.navigation.finance'), icon: 'bi bi-graph-up-arrow', to: '/transfers/finance', routeName: 'transfers-finance' },
])
</script>

<template>
  <div class="transfers-workspace mx-auto w-full max-w-7xl">
    <header class="admin-page-header mb-5">
      <h1>{{ t('transfers.workspaceTitle') }}</h1>
      <p>{{ t('transfers.workspaceSubtitle') }}</p>
    </header>

    <div class="transfers-workspace__grid">
      <aside class="transfers-workspace__sidebar">
        <p class="transfers-workspace__navigation-title">{{ t('transfers.navigation.title') }}</p>
        <Menu :model="items" class="transfers-workspace__menu" unstyled>
          <template #item="{ item }">
            <RouterLink
              :to="item.to"
              :class="['transfers-workspace__link', route.name === item.routeName && 'is-selected']"
              :aria-current="route.name === item.routeName ? 'page' : undefined"
            >
              <i :class="item.icon" aria-hidden="true"></i>
              <span>{{ item.label }}</span>
            </RouterLink>
          </template>
        </Menu>
      </aside>

      <main class="min-w-0">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
.transfers-workspace__grid {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 24px;
}
.transfers-workspace__sidebar {
  position: sticky;
  top: 20px;
  align-self: start;
  min-width: 0;
  padding: 16px;
  border: 1px solid #263653;
  border-radius: 12px;
  background: #101a2e;
  overflow: hidden;
}
.transfers-workspace__navigation-title {
  margin: 0 10px 12px;
  color: #dbe7f8;
  font-size: 14px;
  font-weight: 700;
  text-align: start;
}
.transfers-workspace__menu {
  box-sizing: border-box;
  min-width: 0;
  width: 100%;
}
.transfers-workspace__menu :deep(.p-menu-list) {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.transfers-workspace__menu :deep(.p-menu-item),
.transfers-workspace__menu :deep(.p-menu-item-content) {
  min-width: 0;
  margin: 0;
  padding: 0;
  border-radius: 8px;
  background: transparent;
}
.transfers-workspace__link {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 10px;
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  min-height: 42px;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: #b9c9e1;
  font-size: 14px;
  font-weight: 650;
  line-height: 1.35;
  text-align: start;
}
.transfers-workspace__link:hover { background: #17253c; color: #edf5ff; }
.transfers-workspace__link:focus-visible { outline: 2px solid #62c7ef; outline-offset: 2px; }
.transfers-workspace__link.is-selected { border-color: #2a7094; background: #123b55; color: #85ddff; }
.transfers-workspace__link i { width: 18px; text-align: center; }
@media (max-width: 820px) {
  .transfers-workspace__grid { grid-template-columns: 1fr; }
  .transfers-workspace__sidebar { position: static; }
  .transfers-workspace__navigation-title { display: none; }
  .transfers-workspace__menu :deep(.p-menu-list) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
