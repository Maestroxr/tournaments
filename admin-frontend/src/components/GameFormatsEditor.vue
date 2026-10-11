<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from '@/i18n'
import type { FormatProfile } from '@/types/directPlay'
import GameRuleFields from './game-settings/GameRuleFields.vue'
import AdminNumberField from './game-settings/AdminNumberField.vue'
const profile = defineModel<FormatProfile>({ required: true })
const props = defineProps<{ mode: 'match' | 'money'; errors?: Record<string, string> }>()
const { t } = useI18n()
const stake = ref(100)
const canAdd = computed(
  () =>
    Number.isInteger(stake.value) &&
    stake.value >= 100 &&
    stake.value <= 99999999 &&
    profile.value.stake_amounts.length < 100 &&
    !profile.value.stake_amounts.includes(stake.value),
)
const moneyDoubling = computed({
  get: () => profile.value.doubling_options.includes(true),
  set: (value: boolean) => {
    profile.value.doubling_options = [value]
  },
})
function addStake() {
  if (canAdd.value)
    profile.value.stake_amounts = [...profile.value.stake_amounts, stake.value].sort(
      (a, b) => a - b,
    )
}
const profileError = computed(() => props.errors?.format_profiles ?? props.errors?.profile)
</script>
<template>
  <div class="space-y-6">
    <div class="flex flex-wrap gap-4">
      <label class="flex min-h-11 items-center gap-3"
        ><input
          v-model="profile.enabled"
          type="checkbox"
          class="size-5 accent-[#dfbc7c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#dfbc7c]"
        />{{ t('gameSettings.modeEnabled') }}</label
      >
      <label v-if="mode === 'match'" class="flex min-h-11 items-center gap-3"
        ><input
          v-model="profile.public"
          type="checkbox"
          class="size-5 accent-[#dfbc7c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#dfbc7c]"
        />{{ t('gameSettings.publicTables') }}</label
      >
      <label class="flex min-h-11 items-center gap-3"
        ><input
          v-model="profile.quick"
          type="checkbox"
          class="size-5 accent-[#dfbc7c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#dfbc7c]"
        />{{ t('gameSettings.matchmaking') }}</label
      >
    </div>
    <template v-if="mode === 'match'">
      <GameRuleFields v-model="profile" :error="profileError" />
      <label class="block space-y-2 text-sm"
        ><span>{{ t('gameSettings.maximumCube') }}</span>
        <select
          v-model.number="profile.max_cube"
          class="min-h-11 w-full rounded-lg border border-white/20 bg-neutral-900 px-3 text-neutral-100 focus-visible:outline-2 focus-visible:outline-[#dfbc7c]"
        >
          <option v-for="value in [2, 4, 8, 16, 32, 64]" :key="value" :value="value">
            ×{{ value }}
          </option>
        </select>
      </label>
    </template>
    <template v-else>
      <label class="flex min-h-11 items-center gap-3"
        ><input
          v-model="moneyDoubling"
          type="checkbox"
          class="size-5 accent-[#dfbc7c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#dfbc7c]"
        />{{ t('gameSettings.moneyDoubling') }}</label
      >
      <label class="flex min-h-11 items-center gap-3"
        ><input
          v-model="profile.jacoby"
          type="checkbox"
          class="size-5 accent-[#dfbc7c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#dfbc7c]"
        />{{ t('gameSettings.jacoby') }}</label
      >
      <p class="text-sm leading-relaxed text-neutral-400">
        {{ t('gameSettings.dynamicExposure') }}
      </p>
      <p v-if="profileError" role="alert" class="text-sm text-red-300">{{ profileError }}</p>
    </template>
    <AdminNumberField
      v-model="profile.fee_percent"
      :label="t('gameSettings.winnerFee')"
      :min="0"
      :max="100"
      :step="0.01"
      :error="errors?.format_profiles"
    />
    <fieldset class="space-y-3">
      <legend class="mb-2 text-sm font-semibold">
        {{ t(mode === 'money' ? 'gameSettings.stakesPerPoint' : 'gameSettings.stakesPerMatch') }}
      </legend>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="value in profile.stake_amounts"
          :key="value"
          type="button"
          :aria-label="t('directPlay.removeStake') + ' ' + value"
          class="flex min-h-11 items-center gap-3 rounded-lg border border-white/20 px-3 text-sm hover:border-[#dfbc7c] focus-visible:outline-2 focus-visible:outline-[#dfbc7c]"
          @click="profile.stake_amounts = profile.stake_amounts.filter((item) => item !== value)"
        >
          <span dir="ltr">{{ value.toLocaleString() }}</span
          ><span aria-hidden="true">×</span>
        </button>
      </div>
      <div class="grid items-end gap-3 sm:grid-cols-[1fr_auto]">
        <AdminNumberField
          v-model="stake"
          :label="t('directPlay.newStake')"
          :min="100"
          :max="99999999"
          :required="false"
        />
        <button
          type="button"
          :disabled="!canAdd"
          class="min-h-11 rounded-lg border border-[#dfbc7c] px-4 text-[#dfbc7c] focus-visible:outline-2 focus-visible:outline-[#dfbc7c] disabled:opacity-40"
          @click="addStake"
        >
          {{ t('directPlay.addStake') }}
        </button>
      </div>
      <p class="text-xs text-neutral-400">{{ t('gameSettings.emptyStakes') }}</p>
    </fieldset>
  </div>
</template>
