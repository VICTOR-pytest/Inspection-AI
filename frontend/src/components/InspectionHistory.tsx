import type { InspectionRead } from '../types/inspection'

interface Props {
  inspections: InspectionRead[]
  loading: boolean
  error: string | null
  onLoad: () => void
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function InspectionHistory({ inspections, loading, error, onLoad }: Props) {
  return (
    <div className="panel panel--full">
      <div className="panel-header">
        <div className="panel-icon panel-icon--orange">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </svg>
        </div>
        <div>
          <h2 className="panel-title">Histórico Industrial</h2>
          <p className="panel-subtitle">Últimas 50 inspeções</p>
        </div>
        <button
          className="btn btn--ghost btn--sm"
          style={{ marginLeft: 'auto' }}
          onClick={onLoad}
          disabled={loading}
        >
          {loading ? <span className="spinner spinner--sm" /> : (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M1 4v6h6M23 20v-6h-6" />
              <path d="M20.5 9A9 9 0 0 0 5.6 5.4L1 10M23 14l-4.6 4.6A9 9 0 0 1 3.5 15" />
            </svg>
          )}
          Carregar
        </button>
      </div>

      {error && (
        <div className="alert alert--error">
          <span className="alert-icon">⚠</span>
          {error}
        </div>
      )}

      {loading && inspections.length === 0 && (
        <div className="empty-state">
          <span className="spinner spinner--lg" />
          <p>Carregando histórico…</p>
        </div>
      )}

      {!loading && inspections.length === 0 && !error && (
        <div className="empty-state">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#4B5563" strokeWidth="1.5">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          <p>Nenhuma inspeção encontrada.<br />Clique em <strong>Carregar</strong> para buscar.</p>
        </div>
      )}

      {inspections.length > 0 && (
        <div className="table-wrap">
          <table className="inspection-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Barcode</th>
                <th>Peso (kg)</th>
                <th>Status</th>
                <th>Motivo</th>
                <th>Data/Hora</th>
              </tr>
            </thead>
            <tbody>
              {inspections.map((ins) => (
                <tr key={ins.id} className={ins.is_valid ? 'row-ok' : 'row-fail'}>
                  <td className="mono text-dim">#{ins.id}</td>
                  <td className="mono">{ins.barcode}</td>
                  <td className="mono">{ins.weight.toFixed(3)}</td>
                  <td>
                    <span className={`table-badge ${ins.is_valid ? 'table-badge--ok' : 'table-badge--fail'}`}>
                      {ins.is_valid ? 'APROVADO' : 'REJEITADO'}
                    </span>
                  </td>
                  <td className="text-dim text-sm">{ins.reason ?? '—'}</td>
                  <td className="mono text-sm text-dim">{formatDate(ins.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
