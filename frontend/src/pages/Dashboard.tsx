/**
 * pages/Dashboard.tsx — Sprint 6
 *
 * Dashboard operacional: cards de métricas em tempo real (via WebSocket,
 * sem polling) + gráficos com dados históricos persistidos no banco
 * (via /api/v1/dashboard).
 */
import { useWebSocketInspection } from '../hooks/useWebSocketInspection'
import { useDashboardData } from '../hooks/useDashboardData'
import { MetricCard } from '../components/MetricCard'
import { InspectionsPerHourChart } from '../components/charts/InspectionsPerHourChart'
import { ApprovalBarChart } from '../components/charts/ApprovalBarChart'
import { ErrorRateAreaChart } from '../components/charts/ErrorRateAreaChart'

export function Dashboard() {
  const { metrics, feed, connected } = useWebSocketInspection()
  const { data, loading, error } = useDashboardData(feed.length)

  const approvalRate = metrics.total > 0
    ? Math.round((metrics.approved / metrics.total) * 100)
    : 0

  return (
    <div className="dashboard-s6">
      <div className="dashboard-s6-header">
        <div>
          <h2 className="dashboard-s6-title">Dashboard Operacional</h2>
          <p className="dashboard-s6-sub">
            Métricas em tempo real via WebSocket · histórico persistido no PostgreSQL
          </p>
        </div>
        <span className={`ws-pill ${connected ? 'ws-pill--on' : 'ws-pill--off'}`}>
          <span className="ws-pill-dot" />
          {connected ? 'Conectado' : 'Desconectado'}
        </span>
      </div>

      <div className="metrics-grid-s6">
        <MetricCard label="Total de Inspeções" value={metrics.total} accent="cyan" />
        <MetricCard label="Aprovados" value={metrics.approved} accent="green" />
        <MetricCard label="Reprovados" value={metrics.rejected} accent="red" />
        <MetricCard
          label="Error Rate"
          value={`${(metrics.error_rate * 100).toFixed(1)}%`}
          accent={metrics.error_rate > 0.30 ? 'red' : 'orange'}
        />
        <MetricCard label="FPS Atual" value={metrics.fps.toFixed(1)} accent="cyan" sub="frames/s" />
        <MetricCard label="Taxa de Aprovação" value={`${approvalRate}%`} accent="green" />
      </div>

      {error && <div className="alert alert--error">⚠ {error}</div>}

      <div className="charts-grid-s6">
        <div className="panel chart-panel">
          <h3 className="panel-title">Inspeções por Hora</h3>
          {loading && data.last_24h.length === 0
            ? <div className="chart-empty">Carregando…</div>
            : <InspectionsPerHourChart data={data.last_24h} />}
        </div>

        <div className="panel chart-panel">
          <h3 className="panel-title">Aprovações vs Reprovações</h3>
          {loading && data.last_24h.length === 0
            ? <div className="chart-empty">Carregando…</div>
            : <ApprovalBarChart data={data.last_24h} />}
        </div>

        <div className="panel chart-panel chart-panel--wide">
          <h3 className="panel-title">Taxa de Erro (últimas 24h)</h3>
          {loading && data.last_24h.length === 0
            ? <div className="chart-empty">Carregando…</div>
            : <ErrorRateAreaChart data={data.last_24h} />}
        </div>
      </div>
    </div>
  )
}
