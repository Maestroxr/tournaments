<script setup lang="ts">
import { useI18n } from '@/i18n'

export interface TournamentAttentionItem {
  id: string
  title: string
  detail: string
  action: string
  to: string
  severity: 'critical' | 'warning' | 'info'
}

defineProps<{ items: TournamentAttentionItem[] }>()
const { t } = useI18n()
</script>

<template>
  <section class="attention-panel" :aria-label="t('tournamentOverview.attentionTitle')">
    <header>
      <div>
        <p class="attention-panel__eyebrow">{{ t('tournamentOverview.organizerCheck') }}</p>
        <h2>{{ t('tournamentOverview.attentionTitle') }}</h2>
      </div>
      <span v-if="items.length" class="attention-panel__count">{{ items.length }}</span>
    </header>

    <div v-if="items.length" class="attention-panel__items">
      <article
        v-for="item in items"
        :key="item.id"
        class="attention-item"
        :class="`attention-item--${item.severity}`"
      >
        <span class="attention-item__status" aria-hidden="true">
          <i :class="item.severity === 'critical' ? 'bi bi-exclamation-lg' : item.severity === 'warning' ? 'bi bi-exclamation-triangle' : 'bi bi-info-lg'"></i>
        </span>
        <div>
          <h3>{{ item.title }}</h3>
          <p>{{ item.detail }}</p>
        </div>
        <RouterLink :to="item.to">{{ item.action }}<i class="bi bi-chevron-right rtl:rotate-180" aria-hidden="true"></i></RouterLink>
      </article>
    </div>

    <div v-else class="attention-panel__clear">
      <span><i class="bi bi-check-lg" aria-hidden="true"></i></span>
      <div><h3>{{ t('tournamentOverview.noAttention') }}</h3><p>{{ t('tournamentOverview.noAttentionHint') }}</p></div>
    </div>
  </section>
</template>

<style scoped>
.attention-panel { border: 1px solid #293b59; border-radius: 14px; background: #111b30; padding: 20px; }
.attention-panel > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 15px; }
.attention-panel__eyebrow { margin: 0 0 4px; color: #7890b1; font-size: 10px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; }
.attention-panel h2 { margin: 0; color: #eef4ff; font-size: 16px; font-weight: 680; }
.attention-panel__count { display: grid; min-width: 28px; height: 28px; place-items: center; border-radius: 999px; background: #573226; color: #ffb69e; font-size: 12px; font-weight: 750; }
.attention-panel__items { display: grid; gap: 9px; }
.attention-item { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 13px; border: 1px solid #32435f; border-radius: 10px; background: #162139; }
.attention-item__status { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 8px; background: #263954; color: #9ecbff; }
.attention-item h3, .attention-panel__clear h3 { margin: 0; color: #edf3ff; font-size: 13px; font-weight: 650; }
.attention-item p, .attention-panel__clear p { margin: 3px 0 0; color: #a8bad2; font-size: 11px; line-height: 1.45; }
.attention-item a { display: inline-flex; align-items: center; gap: 5px; border-radius: 7px; padding: 7px 9px; color: #9ed4ff; font-size: 11px; font-weight: 650; white-space: nowrap; }
.attention-item a:hover { background: #223550; }
.attention-item--critical { border-color: #6c3b36; }
.attention-item--critical .attention-item__status { background: #4a2928; color: #ffaaa0; }
.attention-item--warning { border-color: #68542d; }
.attention-item--warning .attention-item__status { background: #45391f; color: #efc969; }
.attention-panel__clear { display: flex; align-items: center; gap: 12px; padding: 14px; border: 1px solid #285e50; border-radius: 10px; background: #15342f; }
.attention-panel__clear > span { display: grid; flex: 0 0 30px; height: 30px; place-items: center; border-radius: 50%; background: #1e765f; color: white; }
@media (max-width: 620px) {
  .attention-item { grid-template-columns: auto minmax(0, 1fr); }
  .attention-item a { grid-column: 2; width: fit-content; padding-inline-start: 0; }
}
</style>
