<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from '@/i18n'

const props = defineProps<{ tournamentId: string; state: string; lifecycleState?: string; loading?: boolean }>()
const route = useRoute()
const { t } = useI18n()

type WorkspaceItem = { id: string; routeName?: string; icon: string; locked?: boolean }

const activeItem = computed(() => {
  const names: Record<string, string> = {
    'tournament-detail': 'overview',
    'tournament-settings': 'settings',
    'tournament-players': 'players',
    'tournament-live': 'live',
    'tournament-bracket': 'bracket',
    'tournament-standings': 'standings',
    'tournament-results': 'results',
  }
  return names[String(route.name ?? '')] ?? ''
})
const competitionLocked = computed(() => !['active', 'finished'].includes(props.state))
const resultsLocked = computed(() => props.state !== 'finished')
const groups = computed<{ id: string; items: WorkspaceItem[] }[]>(() => [
  { id: 'general', items: [{ id: 'overview', routeName: 'tournament-detail', icon: 'bi-grid' }] },
  {
    id: 'before',
    items: [
      { id: 'settings', routeName: 'tournament-settings', icon: 'bi-sliders' },
      { id: 'players', routeName: 'tournament-players', icon: 'bi-people' },
    ],
  },
  {
    id: 'during',
    items: [
      { id: 'live', routeName: 'tournament-live', icon: 'bi-broadcast', locked: competitionLocked.value },
      { id: 'bracket', routeName: 'tournament-bracket', icon: 'bi-diagram-3', locked: competitionLocked.value },
      { id: 'standings', routeName: 'tournament-standings', icon: 'bi-bar-chart', locked: competitionLocked.value },
    ],
  },
  {
    id: 'after',
    items: [{ id: 'results', routeName: 'tournament-results', icon: 'bi-trophy', locked: resultsLocked.value }],
  },
])

function routeFor(item: WorkspaceItem) {
  return { name: item.routeName ?? 'tournament-detail', params: { id: props.tournamentId } }
}
</script>

<template>
  <aside class="workspace-sidebar">
    <RouterLink to="/tournaments" class="workspace-sidebar__back"><i class="bi bi-arrow-left" aria-hidden="true"></i>{{ t('tournamentWorkspace.back') }}</RouterLink>
    <p class="workspace-sidebar__title">{{ t('tournamentWorkspace.navigation') }}</p>
    <nav :aria-label="t('tournamentWorkspace.navigation')">
      <section v-for="group in groups" :key="group.id" class="workspace-sidebar__group">
        <h2 v-if="group.id !== 'general'">{{ t(`tournamentWorkspace.groups.${group.id}`) }}</h2>
        <div class="workspace-sidebar__items">
          <template v-for="item in group.items" :key="item.id">
            <span v-if="item.locked || loading" class="workspace-sidebar__item is-locked" aria-disabled="true" :title="t('tournamentWorkspace.lockedHint')">
              <i :class="['bi', item.icon]" aria-hidden="true"></i><span>{{ t(`tournamentWorkspace.${item.id}`) }}</span><i class="bi bi-lock workspace-sidebar__lock" aria-hidden="true"></i>
            </span>
            <RouterLink v-else :to="routeFor(item)" :class="['workspace-sidebar__item', activeItem === item.id && 'is-selected']" :aria-current="activeItem === item.id ? 'page' : undefined">
              <i :class="['bi', item.icon]" aria-hidden="true"></i><span>{{ t(`tournamentWorkspace.${item.id}`) }}</span>
            </RouterLink>
          </template>
        </div>
      </section>
    </nav>
  </aside>
</template>

<style scoped>
.workspace-sidebar { align-self: start; position: sticky; top: 20px; padding: 15px 12px; border: 1px solid #263653; border-radius: 14px; background: #101a2e; }
.workspace-sidebar__back { display: flex; align-items: center; gap: 8px; padding: 8px; color: #acbdd6; font-size: 12px; }
[dir='rtl'] .workspace-sidebar__back i { transform: rotate(180deg); }
.workspace-sidebar__title { margin: 18px 8px 14px; color: #dbe7f8; font-size: 13px; font-weight: 700; }
.workspace-sidebar nav, .workspace-sidebar__items { display: grid; gap: 5px; }
.workspace-sidebar__group + .workspace-sidebar__group { margin-top: 17px; padding-top: 15px; border-top: 1px solid #263653; }
.workspace-sidebar__group h2 { margin: 0 9px 7px; color: #758bab; font-size: 10px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; }
.workspace-sidebar__item { display: flex; align-items: center; gap: 10px; min-height: 42px; border: 1px solid transparent; border-radius: 9px; padding: 10px; color: #b9c9e1; font-size: 13px; font-weight: 600; }
.workspace-sidebar__item:hover { background: #1b2a43; }
.workspace-sidebar__item.is-selected { background: #12344c; border-color: #256083; color: #80dbff; }
.workspace-sidebar__item.is-locked { color: #667793; cursor: not-allowed; }
.workspace-sidebar__item.is-locked:hover { background: transparent; }
.workspace-sidebar__item > i:first-child { width: 18px; text-align: center; }
.workspace-sidebar__lock { margin-inline-start: auto; font-size: 10px; }
.workspace-sidebar a:focus-visible { outline: 2px solid #80dbff; outline-offset: 3px; }
@media (max-width: 960px) {
  .workspace-sidebar { position: static; padding: 11px; }
  .workspace-sidebar__title { display: none; }
  .workspace-sidebar nav { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-top: 8px; }
  .workspace-sidebar__group + .workspace-sidebar__group { margin: 0; padding: 0; border: 0; }
  .workspace-sidebar__group h2 { margin-bottom: 6px; }
}
@media (max-width: 700px) {
  .workspace-sidebar nav { display: flex; gap: 14px; padding-bottom: 5px; overflow-x: auto; overscroll-behavior-inline: contain; scroll-snap-type: inline proximity; }
  .workspace-sidebar__group { min-width: 155px; scroll-snap-align: start; }
  .workspace-sidebar__group:first-child { min-width: 130px; }
}
</style>
