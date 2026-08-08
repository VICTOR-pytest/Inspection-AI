/**
 * pages/Inspections.tsx — Sprint 6
 *
 * Histórico completo de inspeções: tabela com Data, Produto, Barcode,
 * Peso, Confiança, Status. Filtros por status, produto, barcode e
 * intervalo de datas. Ordenação e paginação.
 */
import { useInspectionsTable } from '../hooks/useInspectionsTable'
import type { SortOption, StatusFilter } from '../types/dashboard'

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

const SORT_LABELS: Record<SortOption, string> = {
  newest:           'Mais recentes',
  oldest:           'Mais antigos',
  confidence_desc:  'Maior confiança',
  confidence_asc:   'Menor confiança',
}

export function Inspections() {
  const { filters, updateFilters, resetFilters, result, totalPages, loading, error } =
    useInspectionsTable()

  return (
    <div className="inspections-s6">
      <div className="dashboard-s6-header">
        <div>
          <h2 className="dashboard-s6-title">Histórico de Inspeções</h2>
          <p className="dashboard-s6-sub">
            {result.total} registro(s) encontrado(s)
          </p>
        </div>
      </div>

      <div className="panel filters-panel">
        <div className="filters-grid">
          <div className="field">
            <label className="field-label">Barcode</label>
            <input
              className="field-input"
              placeholder="ex: 789123456"
              value={filters.barcode}
              onChange={e => updateFilters({ barcode: e.target.value })}
            />
          </div>

          <div className="field">
            <label className="field-label">Produto</label>
            <input
              className="field-input"
              placeholder="ex: Produto Teste A"
              value={filters.productName}
              onChange={e => updateFilters({ productName: e.target.value })}
            />
          </div>

          <div className="field">
            <label className="field-label">Status</label>
            <select
              className="field-input field-select"
              value={filters.status}
              onChange={e => updateFilters({ status: e.target.value as StatusFilter })}
            >
              <option value="all">Todos</option>
              <option value="approved">Aprovados</option>
              <option value="rejected">Reprovados</option>
            </select>
          </div>

          <div className="field">
            <label className="field-label">Data Inicial</label>
            <input
              className="field-input"
              type="date"
              value={filters.dateFrom}
              onChange={e => updateFilters({ dateFrom: e.target.value })}
            />
          </div>

          <div className="field">
            <label className="field-label">Data Final</label>
            <input
              className="field-input"
              type="date"
              value={filters.dateTo}
              onChange={e => updateFilters({ dateTo: e.target.value })}
            />
          </div>

          <div className="field">
            <label className="field-label">Ordenar por</label>
            <select
              className="field-input field-select"
              value={filters.sort}
              onChange={e => updateFilters({ sort: e.target.value as SortOption })}
            >
              {Object.entries(SORT_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
        </div>

        <button className="btn btn--ghost btn--sm" onClick={resetFilters}>
          ↺ Limpar filtros
        </button>
      </div>

      {error && <div className="alert alert--error">⚠ {error}</div>}

      <div className="panel table-panel">
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Data</th>
                <th>Produto</th>
                <th>Barcode</th>
                <th>Peso</th>
                <th>Confiança</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {loading && result.items.length === 0 ? (
                <tr><td colSpan={6} className="table-empty">Carregando…</td></tr>
              ) : result.items.length === 0 ? (
                <tr><td colSpan={6} className="table-empty">Nenhuma inspeção encontrada.</td></tr>
              ) : (
                result.items.map(item => (
                  <tr key={item.id} className={item.valid ? 'row-ok' : 'row-fail'}>
                    <td className="mono">{formatDateTime(item.created_at)}</td>
                    <td>{item.product_name ?? '—'}</td>
                    <td className="mono">{item.barcode}</td>
                    <td className="mono">{item.weight.toFixed(3)} kg</td>
                    <td className="mono">{(item.confidence * 100).toFixed(0)}%</td>
                    <td>
                      <span className={`badge ${item.valid ? 'badge-ok' : 'badge-fail'}`}>
                        {item.valid ? '✓ OK' : '✗ FAIL'}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="pagination">
          <button
            className="btn btn--ghost btn--sm"
            disabled={filters.page <= 1}
            onClick={() => updateFilters({ page: filters.page - 1 })}
          >
            ← Anterior
          </button>
          <span className="pagination-info">
            Página {filters.page} de {totalPages}
          </span>
          <button
            className="btn btn--ghost btn--sm"
            disabled={filters.page >= totalPages}
            onClick={() => updateFilters({ page: filters.page + 1 })}
          >
            Próxima →
          </button>
        </div>
      </div>
    </div>
  )
}
