<script setup lang="ts">
import { computed, provide, ref, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AppAlert from '@/components/AppAlert.vue'
import TournamentStatusBadge from '@/components/TournamentStatusBadge.vue'
import TournamentWorkspaceSidebar from '@/components/tournament/TournamentWorkspaceSidebar.vue'
import { apiFetch, formatApiError } from '@/services/api'
import {
  tournamentWorkspaceKey,
  type TournamentWorkspaceSummary,
} from '@/composables/useTournamentWorkspace'
import { useI18n } from '@/i18n'

const route = useRoute()
const { t } = useI18n()
const tournament = ref<TournamentWorkspaceSummary | null>(null)
const loading = ref(true)
const error = ref('')
const id = computed(() => String(route.params.id))

async function load() {
  loading.value = true
  error.value = ''
  try {
    tournament.value = await apiFetch<TournamentWorkspaceSummary>(
      `/api/admin/tournaments/${id.value}`,
    )
  } catch (caught: unknown) {
    tournament.value = null
    error.value = formatApiError(caught)
  } finally {
    loading.value = false
  }
}

provide(tournamentWorkspaceKey, { tournament, refresh: load })
watch(id, () => void load(), { immediate: true })
</script>

<template>
  <div class="tournament-workspace-layout">
    <TournamentWorkspaceSidebar
      :tournament-id="id"
      :state="tournament?.state ?? ''"
      :lifecycle-state="tournament?.lifecycle_state ?? ''"
      :loading="loading"
    />

    <section class="tournament-workspace-content">
      <header class="tournament-workspace-header">
        <div class="min-w-0">
          <p class="tournament-workspace-header__eyebrow">
            {{ t('tournamentWorkspace.tournamentNumber', { id }) }}
          </p>
          <div class="tournament-workspace-header__title-row">
            <h1>{{ tournament?.name ?? t('tournamentWorkspace.title') }}</h1>
            <TournamentStatusBadge v-if="tournament" :state="tournament.state" />
          </div>
        </div>
        <div v-if="tournament" class="tournament-workspace-header__players">
          <i class="bi bi-people" aria-hidden="true"></i>
          <span>{{
            t('tournamentWorkspace.playerCount', { count: tournament.participant_count })
          }}</span>
        </div>
      </header>

      <div v-if="loading" class="tournament-workspace-loading" role="status">
        <i class="bi bi-arrow-clockwise" aria-hidden="true"></i>
        <span>{{ t('common.loading') }}</span>
      </div>
      <div v-else-if="error" class="tournament-workspace-error">
        <AppAlert type="error" :message="error" />
        <RouterLink to="/tournaments" class="tournament-workspace-return">
          {{ t('common.backTournaments') }}
        </RouterLink>
      </div>
      <RouterView v-else />
    </section>
  </div>
</template>

<style scoped>
.tournament-workspace-layout {
  display: grid;
  grid-template-columns: 230px minmax(0, 1fr);
  gap: 28px;
  width: 100%;
  max-width: 1500px;
  margin: 0 auto;
}
.tournament-workspace-content { min-width: 0; }
.tournament-workspace-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  min-height: 88px;
  margin-bottom: 24px;
  padding: 18px 22px;
  border: 1px solid #263653;
  border-radius: 14px;
  background: linear-gradient(120deg, #111d33, #10182b);
}
.tournament-workspace-header__eyebrow {
  margin-bottom: 5px;
  color: #85a3cf;
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.tournament-workspace-header__title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.tournament-workspace-header h1 {
  overflow-wrap: anywhere;
  color: #f2f6ff;
  font-size: 25px;
  font-weight: 720;
  line-height: 1.25;
}
.tournament-workspace-header__players {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  padding: 9px 12px;
  border: 1px solid #314766;
  border-radius: 9px;
  background: #15233b;
  color: #c4d5ed;
  font-size: 12px;
  font-weight: 650;
}
.tournament-workspace-loading {
  display: flex;
  min-height: 260px;
  align-items: center;
  justify-content: center;
  gap: 9px;
  color: #aab8d4;
}
.tournament-workspace-loading i { animation: workspace-spin 900ms linear infinite; }
.tournament-workspace-error { display: grid; gap: 14px; }
.tournament-workspace-return {
  width: fit-content;
  color: #9fc1ff;
  font-size: 13px;
  font-weight: 650;
}
@keyframes workspace-spin { to { transform: rotate(360deg); } }
@media (max-width: 960px) {
  .tournament-workspace-layout { grid-template-columns: minmax(0, 1fr); gap: 18px; }
}
@media (max-width: 620px) {
  .tournament-workspace-header { align-items: flex-start; flex-direction: column; padding: 16px; }
  .tournament-workspace-header h1 { font-size: 21px; }
  .tournament-workspace-header__players { width: 100%; }
}
</style>
