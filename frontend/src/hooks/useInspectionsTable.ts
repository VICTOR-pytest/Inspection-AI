/**
 * useInspectionsTable.ts — Sprint 6
 *
 * Gerencia estado de filtros + paginação + ordenação da página de Histórico,
 * e busca os dados em /api/v1/inspections sempre que algum filtro muda.
 */
import { useCallback, useEffect, useState } from 'react'
import { api } from '../services/api'
import type { InspectionFilters, PaginatedInspections, StatusFilter } from '../types/dashboard'

const DEFAULT_FILTERS: InspectionFilters = {
  barcode: '',
  productName: '',
  status: 'all',
  dateFrom: '',
  dateTo: '',
  sort: 'newest',
  page: 1,
  pageSize: 20,
}

function statusToValid(status: StatusFilter): boolean | undefined {
  if (status === 'approved') return true
  if (status === 'rejected') return false
  return undefined
}

export function useInspectionsTable() {
  const [filters, setFilters] = useState<InspectionFilters>(DEFAULT_FILTERS)
  const [result, setResult] = useState<PaginatedInspections>({
    items: [], total: 0, page: 1, page_size: 20,
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async (f: InspectionFilters) => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listInspectionsV1({
        barcode: f.barcode || undefined,
        product_name: f.productName || undefined,
        valid: statusToValid(f.status),
        date_from: f.dateFrom ? new Date(f.dateFrom).toISOString() : undefined,
        date_to: f.dateTo ? new Date(f.dateTo + 'T23:59:59').toISOString() : undefined,
        sort: f.sort,
        page: f.page,
        page_size: f.pageSize,
      })
      setResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao buscar inspeções')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData(filters) }, [filters, fetchData])

  const updateFilters = useCallback((partial: Partial<InspectionFilters>) => {
    setFilters(prev => ({
      ...prev,
      ...partial,
      page: 'page' in partial ? (partial.page ?? prev.page) : 1,
    }))
  }, [])

  const resetFilters = useCallback(() => setFilters(DEFAULT_FILTERS), [])

  const totalPages = Math.max(1, Math.ceil(result.total / result.page_size))

  return {
    filters, updateFilters, resetFilters,
    result, totalPages, loading, error,
    refetch: () => fetchData(filters),
  }
}
