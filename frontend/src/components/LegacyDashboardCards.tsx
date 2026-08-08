import type { DashboardMetrics } from '../types/inspection'

interface Props {
  metrics: DashboardMetrics
  lastFetch: Date | null
  onRefresh: () => void
  loading: boolean
}

export function LegacyDashboardCards({ metrics, lastFetch, onRefresh, loading }: Props) {
  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <h2 className="dashboard-title">Métricas da Linha</h2>
        <div className="dashboard-actions">
          {lastFetch && (
            <span className="last-fetch">
              Atualizado às {lastFetch.toLocaleTimeString('pt-BR')}
            </span>
          )}
          <button className="btn btn--ghost btn--sm" onClick={onRefresh} disabled={loading}>
            {loading ? <span className="spinner spinner--sm" /> : (
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M1 4v6h6M23 20v-6h-6" />
                <path d="M20.5 9A9 9 0 0 0 5.6 5.4L1 10M23 14l-4.6 4.6A9 9 0 0 1 3.5 15" />
              </svg>
            )}
            Atualizar
          </button>
        </div>
      </div>

      <div className="dashboard-metrics-grid">
        <div className="metric-card">
          <span className="metric-label">Total</span>
          <span className="metric-value mono">{metrics.total}</span>
        </div>
        <div className="metric-card metric-card--approved">
          <span className="metric-label">Aprovados</span>
          <span className="metric-value mono text-green">{metrics.approved}</span>
        </div>
        <div className="metric-card metric-card--rejected">
          <span className="metric-label">Rejeitados</span>
          <span className="metric-value mono text-red">{metrics.rejected}</span>
        </div>
        <div className="metric-card metric-card--rate">
          <span className="metric-label">Taxa de Aprovação</span>
          <div className="rate-display">
            <span className="metric-value mono">{metrics.approvalRate}</span>
            <span className="metric-unit">%</span>
          </div>
          <div className="rate-bar">
            <div
              className="rate-fill"
              style={{
                width: `${metrics.approvalRate}%`,
                backgroundColor: metrics.approvalRate >= 80 ? '#22c55e' : metrics.approvalRate >= 50 ? '#f59e0b' : '#ef4444',
              }}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
