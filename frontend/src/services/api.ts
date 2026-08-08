import type {
  InspectionRequest,
  InspectionResult,
  InspectionRead,
  RealtimeInspectionRequest,
  RealtimeInspectionResult,
  DecisionRequest,
  DecisionResponse,
} from '../types/inspection'
import type {
  DashboardResponse,
  MetricsResponse,
  PaginatedInspections,
} from '../types/dashboard'

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

let _getToken: (() => string | null) | null = null
let _onUnauthorized: (() => void) | null = null

export function configureAuth(
  getToken: () => string | null,
  onUnauthorized: () => void,
) {
  _getToken = getToken
  _onUnauthorized = onUnauthorized
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = _getToken?.()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options?.headers as Record<string, string>),
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers })

  if (res.status === 401) {
    _onUnauthorized?.()
    throw new Error('Sessão expirada. Faça login novamente.')
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export interface ListInspectionsParams {
  barcode?: string
  valid?: boolean
  product_name?: string
  date_from?: string
  date_to?: string
  sort?: 'newest' | 'oldest' | 'confidence_desc' | 'confidence_asc'
  page?: number
  page_size?: number
  [key: string]: string | number | boolean | undefined
}

function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value))
    }
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

export const api = {
  health: () => request<{ status: string }>('/health'),

  checkInspection: (payload: InspectionRequest) =>
    request<InspectionResult>('/inspection/check', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  realtimeInspection: (payload: RealtimeInspectionRequest) =>
    request<RealtimeInspectionResult>('/inspection/realtime', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  listInspections: () => request<InspectionRead[]>('/inspection/'),

  listInspectionsV1: (params: ListInspectionsParams = {}) =>
    request<PaginatedInspections>(`/api/v1/inspections${buildQuery(params)}`),

  getInspectionV1: (id: number) =>
    request<PaginatedInspections['items'][number]>(`/api/v1/inspections/${id}`),

  getMetrics: () => request<MetricsResponse>('/api/v1/metrics'),

  getDashboard: () => request<DashboardResponse>('/api/v1/dashboard'),

  submitDecision: (inspectionId: number, payload: DecisionRequest) =>
    request<DecisionResponse>(`/api/v1/inspections/${inspectionId}/decision`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
