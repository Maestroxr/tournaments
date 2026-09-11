<script setup lang="ts">
import { computed, ref } from 'vue'
import SelectButton from 'primevue/selectbutton'
import ToggleSwitch from 'primevue/toggleswitch'
import InputNumber from 'primevue/inputnumber'
import Button from 'primevue/button'
import Chip from 'primevue/chip'
import coinIcon from '@/assets/6b-coin.png'
import { useI18n } from '@/i18n'
import type { FormatProfiles } from '@/types/directPlay'
const profiles = defineModel<FormatProfiles>({ required: true })
const { locale } = useI18n()
const he = computed(() => locale.value === 'he')
const selected = ref<'match' | 'money'>('match')
const profile = computed(() => profiles.value[selected.value])
const stake = ref<number | null>(null)
const points = Array.from({ length: 25 }, (_, i) => i + 1)
const clocks = computed(() => [
  { value: 'none', label: he.value ? 'ללא שעון' : 'No clock' },
  { value: 'normal', label: he.value ? 'רגיל' : 'Normal' },
  { value: 'fast', label: he.value ? 'מהיר' : 'Fast' },
  { value: 'slow', label: he.value ? 'איטי' : 'Slow' },
])
const doubling = computed(() => [
  { value: true, label: he.value ? 'עם הכפלה' : 'With cube' },
  { value: false, label: he.value ? 'ללא הכפלה' : 'Without cube' },
])
function addStake() {
  if (!stake.value || !Number.isInteger(stake.value) || stake.value < 100 || stake.value > 99999999 || profile.value.stake_amounts.includes(stake.value)) return
  profile.value.stake_amounts = [...profile.value.stake_amounts, stake.value].sort((a,b) => a-b)
  stake.value = null
}
</script>

<template>
  <section class="formats-editor">
    <SelectButton v-model="selected" :allow-empty="false" option-label="label" option-value="value"
      :options="[{ value: 'match', label: he ? 'סדרה לנקודות' : 'Match play' }, { value: 'money', label: he ? 'מטבעות לנקודה' : 'Money game' }]" />
    <p>{{ selected === 'money'
      ? (he ? 'הקובייה ומכפילי הניצחון קובעים את התשלום, עד תקרת ההפסד. מלוא התקרה משוריינת מכל שחקן בכניסה.' : 'The cube and win type determine payment, capped by the loss limit. Each player reserves the full limit on entry.')
      : (he ? 'סכום קבוע לכל הסדרה. הקובייה מכפילה נקודות בלבד; Crawford חל כששחקן מגיע לראשונה למרחק נקודה מהיעד.' : 'Fixed stake for the whole match. The cube affects points only; Crawford applies the first time a player is one point from the target.') }}</p>
    <div class="format-access">
      <label v-for="flag in (['enabled', 'public', 'private', 'quick'] as const)" :key="flag">
        <ToggleSwitch v-model="profile[flag]" :aria-label="flag" />
        {{ ({ enabled: he ? 'פעיל' : 'Enabled', public: he ? 'שולחן ציבורי' : 'Public tables', private: he ? 'פרטי עם חבר' : 'Private with friend', quick: he ? 'התאמה מהירה' : 'Quick matchmaking' })[flag] }}
      </label>
    </div>
    <fieldset v-if="selected === 'match'"><legend>{{ he ? 'יעדי נקודות זמינים' : 'Available point targets' }}</legend>
      <SelectButton v-model="profile.target_points" :options="points.map(value => ({ value, label: String(value) }))" option-label="label" option-value="value" multiple :allow-empty="false" /></fieldset>
    <fieldset><legend>{{ he ? 'שעונים זמינים' : 'Available clocks' }}</legend>
      <SelectButton v-model="profile.time_controls" :options="clocks" option-label="label" option-value="value" multiple :allow-empty="false" /></fieldset>
    <fieldset><legend>{{ he ? 'אפשרויות הכפלה' : 'Cube options' }}</legend>
      <SelectButton v-model="profile.doubling_options" :options="doubling" option-label="label" option-value="value" multiple :allow-empty="false" /></fieldset>
    <fieldset><legend>{{ he ? 'תקרת קובייה' : 'Maximum cube' }}</legend>
      <SelectButton v-model="profile.max_cube" :options="[2,4,8,16,32,64].map(value => ({ value, label: `×${value}` }))" option-label="label" option-value="value" :allow-empty="false" /></fieldset>
    <div class="format-access" v-if="selected === 'money'">
      <label><ToggleSwitch v-model="profile.jacoby" /> Jacoby</label>
      <label>{{ he ? 'תקרת הפסד × סכום לנקודה' : 'Loss limit × stake per point' }}
        <InputNumber v-model="profile.loss_limit_multiplier" :min="1" :max="192" :max-fraction-digits="0" /></label>
      <small>{{ he ? 'Jacoby: לפני קבלת הכפלה, מארס ובקגמון מחושבים כניצחון רגיל.' : 'Jacoby: before an accepted double, gammons and backgammons count as a single win.' }}</small>
    </div>
    <label>{{ he ? 'עמלה מהרווח של המנצח (%)' : 'Fee on winner’s profit (%)' }}
      <InputNumber v-model="profile.fee_percent" :min="0" :max="100" :max-fraction-digits="2" /></label>
    <fieldset><legend>{{ selected === 'money' ? (he ? 'סכומים לנקודה' : 'Stakes per point') : (he ? 'סכומים לסדרה' : 'Stakes per match') }}</legend>
      <div class="format-stakes"><Chip v-for="value in profile.stake_amounts" :key="value" removable
        @remove="profile.stake_amounts = profile.stake_amounts.filter(x => x !== value)">
        <img :src="coinIcon" alt="6B" /><span>{{ value.toLocaleString() }}</span>
      </Chip></div>
      <div class="format-access"><InputNumber v-model="stake" :min="100" :max="99999999" :max-fraction-digits="0" :aria-label="he ? 'סכום חדש' : 'New stake'" />
        <Button type="button" :label="he ? 'הוסף סכום' : 'Add stake'" @click="addStake" /></div>
      <small>{{ he ? 'רשימה ריקה חוסמת יצירת משחקים בפורמט הזה. שינויים נשמרים באמצעות כפתור השמירה.' : 'An empty list blocks new games in this format. Use Save to apply changes.' }}</small>
    </fieldset>
  </section>
</template>

<style scoped>
.formats-editor { display:grid; gap:24px; }
.formats-editor p, small { color:#afc2df; line-height:1.7; }
.formats-editor fieldset { border:1px solid #2b3e5c; border-radius:12px; padding:18px; min-width:0; }
.formats-editor legend { padding:0 8px; font-weight:700; }
.format-access,.format-stakes { display:flex; flex-wrap:wrap; gap:16px; align-items:center; margin:12px 0; }
.formats-editor label { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.format-stakes img { width:24px; height:24px; object-fit:contain; }
.formats-editor :deep(.p-selectbutton) { flex-wrap:wrap; gap:6px; }
</style>
