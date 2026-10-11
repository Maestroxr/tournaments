import { computed, onUnmounted, ref } from 'vue'
import { t } from '@/i18n'
import { apiFetch, apiFieldErrors, formatApiError } from '@/services/api'
import type { DirectPlaySettings, FormatProfile } from '@/types/directPlay'
import { settingsSections, type GameSettingsForm, type SettingsSection } from '@/types/gameSettings'

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
function normalize(value: DirectPlaySettings): GameSettingsForm {
  if (!value.format_profiles) throw new Error(t('gameSettings.serverUpdateRequired'))
  const match = value.format_profiles.match
  const clocks = value.format_profiles.money.time_controls
  return {
    format_profiles: clone(value.format_profiles),
    friend_rules: {
      ...clone(
        value.friend_rules ?? {
          enabled: match.enabled && match.private,
          target_points: match.target_points,
          time_controls: match.time_controls,
          doubling_options: match.doubling_options,
        },
      ),
      max_cube: value.friend_rules?.max_cube ?? match.max_cube,
    },
    practice_rules: clone(
      value.practice_rules ?? {
        target_points: [1, 3, 5, 7, 9, 11, 15, 21, 25],
        time_controls: ['none', 'fast', 'normal', 'slow'],
      },
    ),
    money_time_control:
      value.money_time_control ?? (clocks.includes('normal') ? 'normal' : (clocks[0] ?? 'normal')),
    enabled: value.enabled,
    friend_game_fee: Number(value.friend_game_fee),
    ai_game_fee: Number(value.ai_game_fee),
    tournament_fee_percent: Number(value.tournament_fee_percent),
    coin_grant_enabled: value.coin_grant_enabled,
    coin_grant_amount: Number(value.coin_grant_amount),
    coin_grant_interval_hours: value.coin_grant_interval_hours,
    game_rules: clone(value.game_rules),
    stake_amounts: [...(value.stake_amounts ?? [])],
    head_to_head_fee_percent: Number(value.head_to_head_fee_percent),
  }
}
const pick = (profile: FormatProfile, keys: (keyof FormatProfile)[]) =>
  Object.fromEntries(keys.map((key) => [key, profile[key]]))
export function sectionPayload(
  form: GameSettingsForm,
  section: SettingsSection,
): Record<string, unknown> {
  switch (section) {
    case 'match':
      return {
        section,
        profile: pick(form.format_profiles.match, [
          'enabled',
          'public',
          'quick',
          'target_points',
          'time_controls',
          'doubling_options',
          'max_cube',
          'stake_amounts',
          'fee_percent',
        ]),
      }
    case 'money':
      return {
        section,
        profile: pick(form.format_profiles.money, [
          'enabled',
          'quick',
          'doubling_options',
          'stake_amounts',
          'fee_percent',
          'jacoby',
        ]),
        money_time_control: form.money_time_control,
      }
    case 'friend':
      return { section, friend_rules: form.friend_rules, friend_game_fee: form.friend_game_fee }
    case 'practice':
      return { section, practice_rules: form.practice_rules, ai_game_fee: form.ai_game_fee }
    case 'tournaments':
      return { section, tournament_fee_percent: form.tournament_fee_percent }
    case 'settings':
      return {
        section,
        enabled: form.enabled,
        coin_grant_enabled: form.coin_grant_enabled,
        coin_grant_amount: form.coin_grant_amount,
        coin_grant_interval_hours: form.coin_grant_interval_hours,
      }
    case 'legacy':
      return {
        section,
        game_rules: form.game_rules,
        stake_amounts: form.stake_amounts,
        head_to_head_fee_percent: form.head_to_head_fee_percent,
      }
  }
}
function copySection(target: GameSettingsForm, source: GameSettingsForm, section: SettingsSection) {
  if (section === 'match' || section === 'money') {
    target.format_profiles[section] = clone(source.format_profiles[section])
    if (section === 'money') target.money_time_control = source.money_time_control
    return
  }
  const values = sectionPayload(source, section)
  delete values.section
  Object.assign(target, clone(values))
}
export function useGameAdminSettings() {
  const form = ref<GameSettingsForm | null>(null)
  const baseline = ref<Partial<Record<SettingsSection, string>>>({})
  const errors = ref<Partial<Record<SettingsSection, string>>>({})
  const fieldErrors = ref<Partial<Record<SettingsSection, Record<string, string>>>>({})
  const saved = ref<Partial<Record<SettingsSection, boolean>>>({})
  const savingSection = ref<SettingsSection | null>(null)
  let live = true
  onUnmounted(() => {
    live = false
  })
  const dirty = computed(
    () =>
      Object.fromEntries(
        settingsSections.map((section) => [
          section,
          !!form.value &&
            JSON.stringify(sectionPayload(form.value, section)) !== baseline.value[section],
        ]),
      ) as Record<SettingsSection, boolean>,
  )
  function accept(value: DirectPlaySettings) {
    if (!live) return
    const next = normalize(value)
    const wasDirty = { ...dirty.value }
    if (!form.value) form.value = next
    else
      for (const section of settingsSections)
        if (!wasDirty[section]) copySection(form.value, next, section)
    for (const section of settingsSections)
      if (!wasDirty[section] || baseline.value[section] === undefined)
        baseline.value[section] = JSON.stringify(sectionPayload(next, section))
  }
  async function save(section: SettingsSection) {
    if (!form.value || savingSection.value || !dirty.value[section]) return
    const payload = clone(sectionPayload(form.value, section))
    savingSection.value = section
    errors.value[section] = ''
    fieldErrors.value[section] = {}
    saved.value[section] = false
    try {
      const response = await apiFetch<DirectPlaySettings>('/api/admin/direct-play/settings', {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
      if (!live || !form.value) return
      const next = normalize(response)
      // Preserve edits in other sections and edits made while this request was pending.
      if (JSON.stringify(sectionPayload(form.value, section)) === JSON.stringify(payload))
        copySection(form.value, next, section)
      baseline.value[section] = JSON.stringify(sectionPayload(next, section))
      saved.value[section] = true
    } catch (error) {
      if (!live) return
      errors.value[section] = formatApiError(error)
      fieldErrors.value[section] = apiFieldErrors(error)
    } finally {
      if (live) savingSection.value = null
    }
  }
  return { form, dirty, errors, fieldErrors, saved, savingSection, accept, save }
}
