export type FinanceRangeDays = 0 | 7 | 30 | 90

export interface FinanceSummary {
  revenue: string
  refunds: string
  prizes: string
  expenses: string
  net: string
  outstanding: string
  outstanding_count: number
}

export interface FinanceTrendPoint {
  date: string
  revenue: string
  expenses: string
  net: string
}

export interface TournamentFinanceRow {
  id: number
  name: string
  revenue: string
  refunds: string
  prizes: string
  expenses: string
  net: string
}

export interface FinanceData {
  updated_at: string
  range_days: FinanceRangeDays
  currency: string
  summary: FinanceSummary
  trend: FinanceTrendPoint[]
  tournaments: TournamentFinanceRow[]
  ignored_transactions: number
}
