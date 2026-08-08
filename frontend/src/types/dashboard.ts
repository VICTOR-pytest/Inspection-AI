// ─── Sprint 6 — Histórico paginado, métricas e dashboard ─────────────────────
// ─── Sprint 9A — campos de decisão humana ────────────────────────────────────

import type { DecisionValue } from './inspection'

export interface InspectionItem {
  id: number
  barcode: string
  valid: boolean
  confidence: number
  weight: number
  product_name: string | null
  reason: string | null
  created_at: string
  // Sprint 9A
  decision: DecisionValue
  decision_reason: string | null
  reviewed_at: string | null
}

export interface PaginatedInspections {
  items: InspectionItem[]
  total: number
  page: number
  page_size: number
}

export interface MetricsResponse {
  total: number
  approved: number
  rejected: number
  error_rate: number
  fps: number
  // Sprint 9A
  decision_approved: number
  decision_rejected: number
  decision_pending: number
  approval_rate: number
  rejection_rate: number
}

export interface HourlyBucket {
  hour: string
  total: number
  approved: number
  rejected: number
}

export interface DashboardResponse {
  total_inspections: number
  approved: number
  rejected: number
  error_rate: number
  last_24h: HourlyBucket[]
  // Sprint 9A
  decision_approved: number
  decision_rejected: number
  decision_pending: number
  approval_rate: number
  rejection_rate: number
}

export type SortOption = 'newest' | 'oldest' | 'confidence_desc' | 'confidence_asc'
export type StatusFilter = 'all' | 'approved' | 'rejected'

export interface InspectionFilters {
  barcode: string
  productName: string
  status: StatusFilter
  dateFrom: string
  dateTo: string
  sort: SortOption
  page: number
  pageSize: number
}
