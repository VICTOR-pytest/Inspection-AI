/**
 * LiveDashboard.tsx — Sprint 5
 * Dashboard industrial em tempo real via WebSocket.
 * Sprint 9A: botões de decisão (Aprovar/Reprovar) com modal de motivo.
 */
import { useState, useCallback } from 'react'
import { useWebSocketInspection } from '../hooks/useWebSocketInspection'
import type { InspectionWSEvent, LiveMetrics } from '../hooks/useWebSocketInspection'
import { api } from '../services/api'
import type { DecisionValue } from '../types/inspection'

// ── Status indicator ─────────────────────────────────────────────────────────

function LineStatusBadge({ status }: { status: LiveMetrics['status'] }) {
  const map = {
    online:     { label: 'LINHA ONLINE',    cls: 'ls-online'     },
    offline:    { label: 'LINHA OFFLINE',   cls: 'ls-offline'    },
    degraded:   { label: 'DEGRADADO',       cls: 'ls-degraded'   },
    connecting: { label: 'CONECTANDO…',     cls: 'ls-connecting' },
  }
  const { label, cls } = map[status]
  return (
    <div className={`line-status ${cls}`}>
      <span className="ls-dot" />
      {label}
    </div>
  )
}

// ── Metric card ───────────────────────────────────────────────────────────────

function MetricCard({
  label, value, sub, accent,
}: { label: string; value: string | number; sub?: string; accent?: string }) {
  return (
    <div className={`metric-card ${accent ?? ''}`}>
      <span className="metric-value">{value}</span>
      <span className="metric-label">{label}</span>
      {sub && <span className="metric-sub">{sub}</span>}
    </div>
  )
}

// ── Sprint 9A — Decision Badge ────────────────────────────────────────────────

function DecisionBadge({ decision }: { decision: DecisionValue | undefined }) {
  const d = decision ?? 'PENDING'
  const map: Record<DecisionValue, { label: string; cls: string }> = {
    PENDING:  { label: '⏳ PENDENTE',  cls: 'dec-pending'  },
    APPROVED: { label: '✓ APROVADO',  cls: 'dec-approved' },
    REJECTED: { label: '✗ REPROVADO', cls: 'dec-rejected' },
  }
  const { label, cls } = map[d]
  return <span className={`decision-badge ${cls}`}>{label}</span>
}

// ── Sprint 9A — Modal de motivo ───────────────────────────────────────────────

interface RejectModalProps {
  inspectionId: number
  onConfirm: (reason: string) => void
  onCancel: () => void
  loading: boolean
}

function RejectModal({ inspectionId, onConfirm, onCancel, loading }: RejectModalProps) {
  const [reason, setReason] = useState('')
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-box" onClick={e => e.stopPropagation()}>
        <h3 className="modal-title">Reprovar inspeção #{inspectionId}</h3>
        <p className="modal-subtitle">Informe o motivo da reprovação:</p>
        <textarea
          className="modal-textarea"
          placeholder="Ex: Rótulo danificado, produto amassado…"
          value={reason}
          onChange={e => setReason(e.target.value)}
          rows={3}
          autoFocus
        />
        <div className="modal-actions">
          <button className="btn-cancel" onClick={onCancel} disabled={loading}>
            Cancelar
          </button>
          <button
            className="btn-reject-confirm"
            onClick={() => onConfirm(reason)}
            disabled={loading || !reason.trim()}
          >
            {loading ? 'Salvando…' : 'Confirmar Reprovação'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Feed row ─────────────────────────────────────────────────────────────────

function YoloBadge({ className, confidence }: { className: string | null; confidence: number }) {
  if (!className) return null
  return (
    <span className="feed-yolo-badge" title={`YOLO: ${className} ${(confidence * 100).toFixed(1)}%`}>
      <span className="feed-yolo-class">{className}</span>
      <span className="feed-yolo-conf">{(confidence * 100).toFixed(0)}%</span>
    </span>
  )
}

function BboxIndicator({ bbox }: { bbox: [number, number, number, number] | null }) {
  if (!bbox) return <span className="feed-bbox feed-bbox--none" title="Sem bounding box">—</span>
  const [x, y, w, h] = bbox
  return (
    <span className="feed-bbox feed-bbox--ok" title={`bbox: x=${x} y=${y} w=${w} h=${h}`}>
      ⬜ {w}×{h}
    </span>
  )
}

function FeedRow({ event }: { event: InspectionWSEvent }) {
  const time = new Date(event.timestamp).toLocaleTimeString('pt-BR')
  const hasYolo = event.yolo_class != null

  // Sprint 9A — estado local de decisão (persiste após chamada à API)
  const [decision, setDecision] = useState<DecisionValue>('PENDING')
  const [showRejectModal, setShowRejectModal] = useState(false)
  const [loadingDecision, setLoadingDecision] = useState(false)
  const [decisionError, setDecisionError] = useState<string | null>(null)

  // inspection_id tipado em InspectionWSEvent (Sprint 9A.1)
  const inspectionId: number | null = event.inspection_id ?? null

  const handleApprove = useCallback(async () => {
    if (!inspectionId) return
    setLoadingDecision(true)
    setDecisionError(null)
    try {
      await api.submitDecision(inspectionId, { decision: 'APPROVED' })
      setDecision('APPROVED')
    } catch (err: unknown) {
      setDecisionError(err instanceof Error ? err.message : 'Erro ao aprovar')
    } finally {
      setLoadingDecision(false)
    }
  }, [inspectionId])

  const handleRejectConfirm = useCallback(async (reason: string) => {
    if (!inspectionId) return
    setLoadingDecision(true)
    setDecisionError(null)
    try {
      await api.submitDecision(inspectionId, { decision: 'REJECTED', reason })
      setDecision('REJECTED')
      setShowRejectModal(false)
    } catch (err: unknown) {
      setDecisionError(err instanceof Error ? err.message : 'Erro ao reprovar')
    } finally {
      setLoadingDecision(false)
    }
  }, [inspectionId])

  return (
    <>
      <div className={`feed-row ${event.valid ? 'feed-ok' : 'feed-fail'} ${hasYolo ? 'feed-row--yolo' : ''}`}>
        <span className={`feed-badge ${event.valid ? 'badge-ok' : 'badge-fail'}`}>
          {event.valid ? '✓ OK' : '✗ FAIL'}
        </span>
        <span className="feed-barcode mono">{event.barcode ?? '—'}</span>
        <span className="feed-product">
          {event.product_name ?? 'Desconhecido'}
          {hasYolo && (
            <YoloBadge className={event.yolo_class} confidence={event.confidence} />
          )}
        </span>
        <span className="feed-weight mono">{event.weight.toFixed(3)} kg</span>
        <span className="feed-conf">{(event.confidence * 100).toFixed(0)}%</span>
        <BboxIndicator bbox={event.bbox ?? null} />
        <span className="feed-time">{time}</span>

        {/* Sprint 9A — badge de decisão */}
        <DecisionBadge decision={decision} />

        {/* Sprint 9A — botões de ação (só aparecem se tiver inspection_id e decisão pendente) */}
        {inspectionId && decision === 'PENDING' && (
          <span className="feed-decision-actions">
            <button
              className="btn-approve"
              onClick={handleApprove}
              disabled={loadingDecision}
              title="Aprovar inspeção"
            >
              ✓ Aprovar
            </button>
            <button
              className="btn-reject"
              onClick={() => setShowRejectModal(true)}
              disabled={loadingDecision}
              title="Reprovar inspeção"
            >
              ✗ Reprovar
            </button>
          </span>
        )}

        {decisionError && (
          <span className="feed-decision-error" title={decisionError}>⚠</span>
        )}

        {event.reason && (
          <span className="feed-reason" title={event.reason}>
            {event.reason.length > 55 ? event.reason.slice(0, 55) + '…' : event.reason}
          </span>
        )}
      </div>

      {showRejectModal && inspectionId && (
        <RejectModal
          inspectionId={inspectionId}
          onConfirm={handleRejectConfirm}
          onCancel={() => setShowRejectModal(false)}
          loading={loadingDecision}
        />
      )}
    </>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function LiveDashboard({ getToken }: { getToken?: () => string | null }) {
  const { feed, metrics, connected, clearFeed } = useWebSocketInspection(getToken)

  const approvalRate = metrics.total
    ? Math.round((metrics.approved / metrics.total) * 100)
    : 0

  return (
    <div className="live-dashboard">

      {/* ── Top bar ── */}
      <div className="live-topbar">
        <div className="live-title">
          <span className={`ws-dot ${connected ? 'ws-dot--on' : 'ws-dot--off'}`} />
          Dashboard Industrial — Tempo Real
        </div>
        <div className="live-actions">
          <LineStatusBadge status={metrics.status} />
          <button className="btn btn-ghost btn-sm" onClick={clearFeed}
                  disabled={feed.length === 0}>
            🗑 Limpar feed
          </button>
        </div>
      </div>

      {/* ── Metrics row ── */}
      <div className="metrics-grid">
        <MetricCard label="Processados"  value={metrics.total}    accent="mc-neutral" />
        <MetricCard label="Aprovados"    value={metrics.approved} accent="mc-green"   />
        <MetricCard label="Rejeitados"   value={metrics.rejected} accent="mc-red"     />
        <MetricCard label="Aprovação"    value={`${approvalRate}%`} accent="mc-blue"  />
        <MetricCard label="Taxa de erro" value={`${(metrics.error_rate * 100).toFixed(1)}%`}
                    accent={metrics.error_rate > 0.30 ? 'mc-red' : 'mc-neutral'} />
        <MetricCard label="FPS"          value={metrics.fps.toFixed(1)}
                    sub="frames/s" accent="mc-neutral" />
      </div>

      {/* ── Sprint 9A — Métricas de decisão humana ── */}
      <div className="decision-metrics-panel">
        <div className="decision-metrics-header">
          <span className="decision-metrics-title">⚖️ Decisões do Operador</span>
        </div>
        <div className="decision-metrics-grid">
          <div className="decision-metric decision-metric--approved">
            <span className="dm-value">{metrics.decision_approved}</span>
            <span className="dm-label">Aprovados</span>
          </div>
          <div className="decision-metric decision-metric--rejected">
            <span className="dm-value">{metrics.decision_rejected}</span>
            <span className="dm-label">Reprovados</span>
          </div>
          <div className="decision-metric decision-metric--pending">
            <span className="dm-value">{metrics.decision_pending}</span>
            <span className="dm-label">Pendentes</span>
          </div>
          <div className="decision-metric decision-metric--rate">
            <span className="dm-value">
              {(metrics.approval_rate * 100).toFixed(1)}%
            </span>
            <span className="dm-label">Taxa Aprovação</span>
          </div>
          <div className="decision-metric decision-metric--rate-rej">
            <span className="dm-value">
              {(metrics.rejection_rate * 100).toFixed(1)}%
            </span>
            <span className="dm-label">Taxa Rejeição</span>
          </div>
        </div>
      </div>

      {/* ── Última detecção YOLO ── */}
      {feed.length > 0 && feed[0].yolo_class && (
        <div className="yolo-detection-panel">
          <div className="yolo-panel-header">
            <span className="yolo-panel-title">
              <span className="yolo-dot" />
              Última Detecção YOLO
            </span>
            <span className="yolo-panel-time">
              {new Date(feed[0].timestamp).toLocaleTimeString('pt-BR')}
            </span>
          </div>
          <div className="yolo-panel-body">
            <div className="yolo-stat">
              <span className="yolo-stat-label">Classe</span>
              <span className="yolo-stat-value yolo-class-name">{feed[0].yolo_class}</span>
            </div>
            <div className="yolo-stat">
              <span className="yolo-stat-label">Confidence</span>
              <div className="yolo-conf-wrap">
                <div
                  className={`yolo-conf-bar ${feed[0].valid ? 'yolo-conf-bar--ok' : 'yolo-conf-bar--fail'}`}
                  style={{ width: `${(feed[0].confidence * 100).toFixed(0)}%` }}
                />
                <span className="yolo-conf-pct mono">{(feed[0].confidence * 100).toFixed(1)}%</span>
              </div>
            </div>
            {feed[0].bbox && (
              <div className="yolo-stat">
                <span className="yolo-stat-label">Bounding Box</span>
                <span className="yolo-stat-value mono">
                  x={feed[0].bbox[0]} y={feed[0].bbox[1]} &nbsp;
                  {feed[0].bbox[2]}×{feed[0].bbox[3]}px
                </span>
              </div>
            )}
            {feed[0].all_detections && feed[0].all_detections.length > 1 && (
              <div className="yolo-stat">
                <span className="yolo-stat-label">Outros objetos</span>
                <span className="yolo-stat-value">
                  {feed[0].all_detections.slice(1, 4).map((d, i) => (
                    <span key={i} className="yolo-secondary-det">
                      {d.class_name} {(d.confidence * 100).toFixed(0)}%
                    </span>
                  ))}
                </span>
              </div>
            )}
            <div className={`yolo-status-badge ${feed[0].valid ? 'yolo-status--ok' : 'yolo-status--fail'}`}>
              {feed[0].valid ? '✓ APROVADO' : '✗ REPROVADO'}
            </div>
          </div>
        </div>
      )}

      {/* ── Live feed ── */}
      <div className="feed-header">
        <span className="feed-title">Feed da Esteira</span>
        <span className="feed-count">{feed.length} eventos</span>
      </div>

      <div className="feed-list">
        {feed.length === 0 ? (
          <div className="feed-empty">
            {connected
              ? 'Aguardando eventos da linha de produção…'
              : 'Conectando ao backend…'}
          </div>
        ) : (
          feed.map((ev, i) => <FeedRow key={`${ev.timestamp}-${i}`} event={ev} />)
        )}
      </div>
    </div>
  )
}
