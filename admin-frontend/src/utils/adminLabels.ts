type Translate = (key: string, params?: Record<string, string | number>) => string

const BANK_SECONDS_PER_POINT: Record<string, number> = {
  fast: 30,
  normal: 60,
  slow: 120,
}

function formatClockUnit(count: number, singularKey: string, pluralKey: string, translate: Translate): string {
  return translate(count === 1 ? singularKey : pluralKey, { count })
}

function formatClockDuration(seconds: number, translate: Translate): string {
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  if (!minutes) return formatClockUnit(remainder, 'tournaments.clockSecond', 'tournaments.clockSeconds', translate)
  if (!remainder) return formatClockUnit(minutes, 'tournaments.clockMinute', 'tournaments.clockMinutes', translate)
  return `${formatClockUnit(minutes, 'tournaments.clockMinute', 'tournaments.clockMinutes', translate)} ${formatClockUnit(remainder, 'tournaments.clockSecond', 'tournaments.clockSeconds', translate)}`
}

export function tournamentStateLabel(state: string, translate?: Translate): string {
  if (translate && ['draft', 'open', 'active', 'finished'].includes(state)) {
    return translate(`dashboard.states.${state}`)
  }
  if (state === 'draft') return 'Draft setup'
  if (state === 'open') return 'Open for registration'
  if (state === 'active') return 'In progress'
  if (state === 'finished') return 'Completed'
  return state
}

export function tournamentStateFilterLabel(state: string, translate?: Translate): string {
  if (translate) {
    if (state === 'current') return translate('tournaments.filters.current')
    if (state === 'all') return translate('tournaments.filters.all')
    if (state === 'finished') return translate('tournaments.filters.finished')
    if (['draft', 'open', 'active'].includes(state)) return translate(`dashboard.states.${state}`)
  }
  if (state === 'current') return 'Current tournaments'
  if (state === 'all') return 'All tournament states'
  if (state === 'draft') return 'Draft setup'
  if (state === 'open') return 'Open for registration'
  if (state === 'active') return 'In progress'
  if (state === 'finished') return 'Completed / results'
  return state
}

export function timeControlDetail(value: string, targetPoints?: number, translate?: Translate): string {
  if (translate && BANK_SECONDS_PER_POINT[value]) {
    const secondsPerPoint = BANK_SECONDS_PER_POINT[value]
    const points = Number.isFinite(targetPoints) && Number(targetPoints) > 0 ? Number(targetPoints) : 1
    return translate('tournaments.timeControlDetail', {
      bank: formatClockDuration(secondsPerPoint * points, translate),
      rate: formatClockDuration(secondsPerPoint, translate),
    })
  }
  return value
}

export function timeControlLabel(value: string, targetPoints?: number, translate?: Translate): string {
  if (translate) {
    if (value === 'none') return translate('tournaments.noClock')
    if (BANK_SECONDS_PER_POINT[value]) {
      return translate('tournaments.timeControlSummary', {
        pace: translate(`tournaments.${value}`),
        detail: timeControlDetail(value, targetPoints, translate),
      })
    }
  }
  if (value === 'none') return 'No clock'
  if (value === 'fast') return 'Fast clock'
  if (value === 'normal') return 'Standard clock'
  if (value === 'slow') return 'Slow clock'
  return value
}

export function transferKindLabel(kind: string, translate?: Translate): string {
  if (translate && ['deposit', 'withdrawal', 'tournament_entry', 'tournament_refund', 'tournament_prize'].includes(kind)) {
    return translate(`transfers.kinds.${kind}`)
  }
  if (kind === 'deposit') return 'Admin deposit'
  if (kind === 'withdrawal') return 'Admin withdrawal'
  if (kind === 'tournament_entry') return 'Tournament entry fee'
  if (kind === 'tournament_refund') return 'Tournament refund'
  if (kind === 'tournament_prize') return 'Tournament prize'
  return kind.replaceAll('_', ' ')
}
