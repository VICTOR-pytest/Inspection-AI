import { useState, useCallback } from 'react'
import { api } from '../services/api'
import type { InspectionRead, DashboardMetrics } from '../types/inspection'

export function useHistory() {
  const [inspections, setInspections] = useState<InspectionRead[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastFetch, setLastFetch] = useState<Date | null>(null)

  const fetch = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listInspections()
      setInspections(data)
      setLastFetch(new Date())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao carregar histórico')
    } finally {
      setLoading(false)
    }
  }, [])

  const metrics: DashboardMetrics = {
    total: inspections.length,
    approved: inspections.filter((i) => i.is_valid).length,
    rejected: inspections.filter((i) => !i.is_valid).length,
    approvalRate:
      inspections.length > 0
        ? Math.round((inspections.filter((i) => i.is_valid).length / inspections.length) * 100)
        : 0,
  }

  return { inspections, loading, error, lastFetch, fetch, metrics }
}
