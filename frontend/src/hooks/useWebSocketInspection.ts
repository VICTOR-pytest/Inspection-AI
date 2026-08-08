/**
 * useWebSocketInspection.ts — Sprint 5
 *
 * Conecta em ws://host/ws/inspection e recebe eventos em tempo real.
 * ❌ Proibido: setInterval, polling HTTP
 * ✔  Apenas WebSocket nativo
 */
import { useCallback, useEffect, useRef, useState } from 'react'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface InspectionWSEvent {
  type:         'inspection'
  barcode:      string | null
  valid:        boolean
  confidence:   number
  weight:       number
  product_name: string | null
  reason:       string | null
  timestamp:    string
  // Sprint 9A.1 — ID da inspeção persistida (necessário para decisão humana)
  inspection_id: number | null
  // Sprint 8B — campos de detecção YOLO (opcionais — null em FallbackDetector)
  yolo_class:      string | null
  bbox:            [number, number, number, number] | null
  all_detections:  Array<{ class_name: string; confidence: number; bbox: [number, number, number, number] }>
}

export interface LineStatusWSEvent {
  type:       'line_status'
  status:     'online' | 'offline' | 'degraded'
  total:      number
  approved:   number
  rejected:   number
  error_rate: number
  fps:        number
  timestamp:  string
  // Campos de decisão opcionais — podem ser enriquecidos futuramente
  decision_approved?: number
  decision_rejected?: number
  decision_pending?:  number
  approval_rate?:     number
  rejection_rate?:    number
}

export type WSEvent = InspectionWSEvent | LineStatusWSEvent

export interface LiveMetrics {
  total:      number
  approved:   number
  rejected:   number
  error_rate: number
  fps:        number
  status:     'online' | 'offline' | 'degraded' | 'connecting'
  // Sprint 9A — métricas de decisão humana (vindas do status_snapshot via polling ou WS)
  decision_approved: number
  decision_rejected: number
  decision_pending:  number
  approval_rate:     number
  rejection_rate:    number
}

// ── Hook ──────────────────────────────────────────────────────────────────────

const WS_BASE = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000')
  .replace(/^http/, 'ws')

const MAX_FEED = 60

export function useWebSocketInspection(getToken?: () => string | null) {
  const [feed,    setFeed]    = useState<InspectionWSEvent[]>([])
  const [metrics, setMetrics] = useState<LiveMetrics>({
    total: 0, approved: 0, rejected: 0,
    error_rate: 0, fps: 0, status: 'connecting',
    decision_approved: 0, decision_rejected: 0, decision_pending: 0,
    approval_rate: 0, rejection_rate: 0,
  })
  const [connected, setConnected] = useState(false)

  const wsRef        = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef   = useRef(true)

  const connect = useCallback(() => {
    if (!mountedRef.current) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const token  = getToken?.()
    const wsUrl  = token
      ? `${WS_BASE}/ws/inspection?token=${token}`
      : `${WS_BASE}/ws/inspection`

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) return
      setConnected(true)
      setMetrics(m => ({ ...m, status: 'online' }))
    }

    ws.onmessage = (e) => {
      if (!mountedRef.current) return
      try {
        const event: WSEvent = JSON.parse(e.data)

        if (event.type === 'inspection') {
          setFeed(prev => [event, ...prev].slice(0, MAX_FEED))
        }

        if (event.type === 'line_status') {
          setMetrics(prev => ({
            ...prev,                      // preserva decision_* existentes
            total:      event.total,
            approved:   event.approved,
            rejected:   event.rejected,
            error_rate: event.error_rate,
            fps:        event.fps,
            status:     event.status,
            // Atualiza campos de decisão se vieram no evento (futuro)
            ...(event.decision_approved !== undefined && { decision_approved: event.decision_approved }),
            ...(event.decision_rejected !== undefined && { decision_rejected: event.decision_rejected }),
            ...(event.decision_pending  !== undefined && { decision_pending:  event.decision_pending  }),
            ...(event.approval_rate     !== undefined && { approval_rate:     event.approval_rate     }),
            ...(event.rejection_rate    !== undefined && { rejection_rate:    event.rejection_rate    }),
          }))
        }
      } catch { /* ignore malformed */ }
    }

    ws.onclose = () => {
      if (!mountedRef.current) return
      setConnected(false)
      setMetrics(m => ({ ...m, status: 'offline' }))
      // Reconecta após 3 s
      reconnectRef.current = setTimeout(connect, 3000)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    connect()
    return () => {
      mountedRef.current = false
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  const clearFeed = useCallback(() => setFeed([]), [])

  return { feed, metrics, connected, clearFeed }
}
