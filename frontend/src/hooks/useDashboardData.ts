/**
 * useDashboardData.ts — Sprint 6
 *
 * Busca o payload agregado de /api/v1/dashboard (totais + série das últimas 24h).
 * Atualização disparada por refreshSignal (mudança no feed do WebSocket),
 * com debounce e retry agendado — evita polling HTTP fixo.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../services/api'
import type { DashboardResponse } from '../types/dashboard'

const EMPTY: DashboardResponse = {
  total_inspections: 0,
  approved: 0,
  rejected: 0,
  error_rate: 0,
  last_24h: [],
  decision_approved: 0,
  decision_rejected: 0,
  decision_pending:  0,
  approval_rate:     0,
  rejection_rate:    0,
}

const MIN_REFRESH_INTERVAL_MS = 3000

export function useDashboardData(refreshSignal: number) {
  const [data, setData] = useState<DashboardResponse>(EMPTY)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const lastFetchRef = useRef(0)
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchNow = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await api.getDashboard()
      setData(result)
      lastFetchRef.current = Date.now()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao buscar dashboard')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchNow() }, [fetchNow])

  useEffect(() => {
    if (refreshSignal === 0) return

    const elapsed = Date.now() - lastFetchRef.current
    if (elapsed >= MIN_REFRESH_INTERVAL_MS) {
      fetchNow()
      return
    }

    if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    retryTimerRef.current = setTimeout(fetchNow, MIN_REFRESH_INTERVAL_MS - elapsed)

    return () => {
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    }
  }, [refreshSignal, fetchNow])

  return { data, loading, error, refetch: fetchNow }
}
