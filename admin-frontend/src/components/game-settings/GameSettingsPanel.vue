<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from '@/i18n'
import type { GameSettingsForm, SettingsSection } from '@/types/gameSettings'
import GameFormatsEditor from '../GameFormatsEditor.vue'
import GameRuleFields from './GameRuleFields.vue'
import AdminChoiceGroup from './AdminChoiceGroup.vue'
import AdminNumberField from './AdminNumberField.vue'
const form = defineModel<GameSettingsForm>({ required: true })
const props = defineProps<{ section: SettingsSection; errors: Record<string, string> }>()
const { t } = useI18n()
const clocks = computed(() =>
  ['none', 'normal', 'fast', 'slow'].map((value) => ({
    value,
    label: t('directPlay.ruleClocks.' + value),
  })),
)
const practicePoints = [1, 3, 5, 7, 9, 11, 15, 21, 25].map((value) => ({
  value,
  label: String(value),
}))
const friendExamples = computed(() =>
  form.value.friend_rules.target_points
    .map((points) => points + ': ' + (points * form.value.friend_game_fee).toLocaleString())
    .join(' · '),
)
const fieldError = (key: string) => props.errors[key]
</script>
<template>
  <div class="space-y-6">
    <template v-if="section === 'match' || section === 'money'">
      <GameFormatsEditor v-model="form.format_profiles[section]" :mode="section" :errors="errors" />
      <label v-if="section === 'money'" class="block space-y-2 text-sm">
        <span>{{ t('gameSettings.fixedClock') }}</span>
        <select
          v-model="form.money_time_control"
          :aria-invalid="Boolean(fieldError('money_time_control'))"
          aria-describedby="money-clock-help"
          class="min-h-11 w-full rounded-lg border border-white/20 bg-neutral-900 px-3 text-neutral-100 focus-visible:outline-2 focus-visible:outline-[#dfbc7c]"
        >
          <option v-for="clock in clocks" :key="clock.value" :value="clock.value">
            {{ clock.label }}
          </option>
        </select>
        <span id="money-clock-help" class="block text-xs text-neutral-400"
          >{{ t('gameSettings.fixedClockHint')
          }}<span v-if="fieldError('money_time_control')" class="block text-red-300">{{
            fieldError('money_time_control')
          }}</span></span
        >
      </label>
    </template>
    <template v-else-if="section === 'friend'">
      <label class="flex min-h-11 items-center gap-3"
        ><input
          v-model="form.friend_rules.enabled"
          type="checkbox"
          class="size-5 accent-[#dfbc7c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#dfbc7c]"
        />{{ t('gameSettings.modeEnabled') }}</label
      >
      <GameRuleFields v-model="form.friend_rules" :error="fieldError('friend_rules')" />
      <label class="block space-y-2 text-sm"
        ><span>{{ t('gameSettings.maximumCube') }}</span>
        <select
          v-model.number="form.friend_rules.max_cube"
          class="min-h-11 w-full rounded-lg border border-white/20 bg-neutral-900 px-3 text-neutral-100 focus-visible:outline-2 focus-visible:outline-[#dfbc7c]"
        >
          <option v-for="value in [2, 4, 8, 16, 32, 64]" :key="value" :value="value">
            ×{{ value }}
          </option>
        </select>
      </label>
      <p class="text-xs text-neutral-400">{{ t('gameSettings.friendTargetsHint') }}</p>
      <AdminNumberField
        v-model="form.friend_game_fee"
        :label="t('gameSettings.friendPrice')"
        :min="0.01"
        :step="0.01"
        :hint="t('gameSettings.friendPriceHint')"
        :error="fieldError('friend_game_fee')"
      />
      <p class="text-sm leading-relaxed text-[#dfbc7c]">
        {{ t('gameSettings.friendExamples') }}
        <span dir="ltr" class="inline-block">{{ friendExamples }}</span>
      </p>
    </template>
    <template v-else-if="section === 'practice'">
      <AdminNumberField
        v-model="form.ai_game_fee"
        :label="t('directPlay.aiGameFee')"
        :min="0"
        :step="0.01"
        :hint="t('directPlay.aiGameFeeHint')"
        :error="fieldError('ai_game_fee')"
      />
      <AdminChoiceGroup
        v-model="form.practice_rules.target_points"
        :options="practicePoints"
        :label="t('directPlay.allowedPoints')"
      />
      <AdminChoiceGroup
        v-model="form.practice_rules.time_controls"
        :options="clocks"
        :label="t('gameSettings.playerClocks')"
        :error="fieldError('practice_rules')"
      />
    </template>
    <template v-else-if="section === 'tournaments'">
      <AdminNumberField
        v-model="form.tournament_fee_percent"
        :label="t('directPlay.tournamentFee')"
        :min="8"
        :max="10"
        :step="0.01"
        :hint="t('directPlay.tournamentFeeHint')"
        :error="fieldError('tournament_fee_percent')"
      />
      <p class="text-sm leading-relaxed text-neutral-400">
        {{ t('gameSettings.tournamentClockHint') }}
      </p>
      <RouterLink
        :to="{ name: 'tournaments' }"
        class="inline-flex min-h-11 items-center rounded-lg border border-[#dfbc7c]/50 px-4 text-[#dfbc7c] focus-visible:outline-2 focus-visible:outline-[#dfbc7c]"
        >{{ t('gameSettings.manageTournaments') }}</RouterLink
      >
    </template>
    <template v-else-if="section === 'settings'">
      <label class="flex min-h-11 items-center gap-3"
        ><input
          v-model="form.enabled"
          type="checkbox"
          class="size-5 accent-[#dfbc7c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#dfbc7c]"
        />{{ t('gameSettings.allDirectPlay') }}</label
      >
      <p class="text-xs text-neutral-400">{{ t('gameSettings.globalHint') }}</p>
      <label class="flex min-h-11 items-center gap-3"
        ><input
          v-model="form.coin_grant_enabled"
          type="checkbox"
          class="size-5 accent-[#dfbc7c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#dfbc7c]"
        />{{ t('directPlay.coinGrantEnabled') }}</label
      >
      <AdminNumberField
        v-model="form.coin_grant_amount"
        :label="t('directPlay.coinGrantAmount')"
        :min="0.01"
        :step="0.01"
        :error="fieldError('coin_grant_amount')"
      />
      <AdminNumberField
        v-model="form.coin_grant_interval_hours"
        :label="t('directPlay.coinGrantInterval')"
        :min="1"
        :max="32767"
        :error="fieldError('coin_grant_interval_hours')"
      />
    </template>
    <template v-else>
      <p
        class="rounded-lg border border-amber-400/30 bg-amber-400/5 p-4 text-sm leading-relaxed text-amber-200"
      >
        {{ t('gameSettings.legacyHint') }}
      </p>
      <details
        v-for="mode in ['match', 'friend', 'quick'] as const"
        :key="mode"
        class="rounded-lg border border-white/15 p-4"
      >
        <summary
          class="min-h-11 cursor-pointer text-sm font-semibold focus-visible:outline-2 focus-visible:outline-[#dfbc7c]"
        >
          {{ t('directPlay.modes.' + mode) }}
        </summary>
        <label class="mb-4 flex min-h-11 items-center gap-3"
          ><input
            v-model="form.game_rules[mode].enabled"
            type="checkbox"
            class="size-5 accent-[#dfbc7c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#dfbc7c]"
          />{{ t('gameSettings.modeEnabled') }}</label
        >
        <GameRuleFields
          v-model="form.game_rules[mode]"
          :target-options="mode === 'friend' ? [1, 3, 5, 7, 9] : undefined"
          :error="fieldError('game_rules')"
        />
      </details>
      <AdminNumberField
        v-model="form.head_to_head_fee_percent"
        :label="t('gameSettings.legacyFee')"
        :min="0"
        :max="100"
        :step="0.01"
        :error="fieldError('head_to_head_fee_percent')"
      />
      <p class="text-sm text-neutral-400">
        {{ t('gameSettings.legacyStakes') }}
        <span dir="ltr" class="inline-block">{{ form.stake_amounts.join(', ') }}</span>
      </p>
    </template>
  </div>
</template>
