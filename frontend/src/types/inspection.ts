// ─── Manual Inspection ───────────────────────────────────────────────────────

export interface InspectionRequest {
  barcode: string
  weight: number
}

export interface InspectionResult {
  barcode_ok: boolean
  weight_ok: boolean
  valid: boolean
  product_name: string | null
  reason: string | null
}

// ─── Realtime Inspection ─────────────────────────────────────────────────────

export interface RealtimeInspectionRequest {
  image: string
  weight: number
}

export interface RealtimeInspectionResult {
  barcode: string | null
  product_name: string | null
  valid: boolean
  barcode_ok: boolean
  weight_ok: boolean
  reason: string | null
  detected: boolean
  detection_confidence: number
}

// ─── History ─────────────────────────────────────────────────────────────────

export interface InspectionRead {
  id: number
  barcode: string
  weight: number
  is_valid: boolean
  reason: string | null
  created_at: string
  product_id: number | null
}

// ─── Dashboard metrics ───────────────────────────────────────────────────────

export interface DashboardMetrics {
  total: number
  approved: number
  rejected: number
  approvalRate: number
}

// ─── Sprint 9A — Decisão humana ──────────────────────────────────────────────

export type DecisionValue = 'PENDING' | 'APPROVED' | 'REJECTED'

export interface DecisionRequest {
  decision: DecisionValue
  reason?: string
}

export interface DecisionResponse {
  id: number
  barcode: string
  weight: number
  is_valid: boolean
  confidence: number
  product_name: string | null
  reason: string | null
  created_at: string
  decision: DecisionValue
  decision_reason: string | null
  reviewed_at: string | null
}
