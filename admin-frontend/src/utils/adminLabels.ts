type Translate = (key: string) => string

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

export function timeControlLabel(value: string, translate?: Translate): string {
  if (translate) {
    if (value === 'none') return translate('tournaments.noClock')
    if (['fast', 'normal', 'slow'].includes(value)) return translate(`tournaments.${value}`)
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
