import { useManualVisionInspection, REALTIME_PRESETS } from '../hooks/useManualVisionInspection'
import { StatusBadge } from './StatusBadge'

export function RealtimeSimulation() {
  const {
    presetIndex,
    setPresetIndex,
    customWeight,
    setCustomWeight,
    preset,
    result,
    loading,
    error,
    simulate,
    reset,
  } = useManualVisionInspection()

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-icon panel-icon--cyan">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3" />
            <path d="M3 12h1M20 12h1M12 3v1M12 20v1M5.6 5.6l.7.7M17.7 17.7l.7.7M5.6 18.4l.7-.7M17.7 6.3l.7-.7" />
          </svg>
        </div>
        <div>
          <h2 className="panel-title">Simulação Realtime</h2>
          <p className="panel-subtitle">Pipeline via imagem — visão no backend</p>
        </div>
      </div>

      <div className="field">
        <label className="field-label">Cenário de Simulação</label>
        <select
          className="field-input field-select"
          value={presetIndex}
          onChange={(e) => { setPresetIndex(Number(e.target.value)); reset() }}
        >
          {REALTIME_PRESETS.map((p, i) => (
            <option key={i} value={i}>{p.label}</option>
          ))}
        </select>
      </div>

      <div className="preset-info">
        <div className="preset-row">
          <span className="preset-key">Barcode</span>
          <span className="preset-val mono">{preset.barcode || '— (sem barcode)'}</span>
        </div>
        <div className="preset-row">
          <span className="preset-key">Peso padrão</span>
          <span className="preset-val mono">{preset.weight} kg</span>
        </div>
      </div>

      <div className="field">
        <label className="field-label">Sobrepor peso (opcional)</label>
        <input
          className="field-input"
          type="number"
          step="0.01"
          min="0"
          placeholder={`Padrão: ${preset.weight} kg`}
          value={customWeight}
          onChange={(e) => setCustomWeight(e.target.value)}
        />
      </div>

      <div className="button-row">
        <button className="btn btn--cyan" onClick={simulate} disabled={loading}>
          {loading ? (
            <>
              <span className="scanner-pulse" />
              Processando…
            </>
          ) : (
            <>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{marginRight: 6}}>
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
              Simular Inspeção
            </>
          )}
        </button>
        {result && (
          <button className="btn btn--ghost" onClick={reset}>Limpar</button>
        )}
      </div>

      {error && (
        <div className="alert alert--error">
          <span className="alert-icon">⚠</span>
          {error}
        </div>
      )}

      {result && (
        <div className={`result-card ${result.valid ? 'result-card--approved' : 'result-card--rejected'}`}>
          <div className="result-header">
            <StatusBadge valid={result.valid} size="lg" />
            {result.product_name && (
              <span className="result-product">{result.product_name}</span>
            )}
          </div>

          <div className="realtime-grid">
            <div className="rt-field">
              <span className="rt-label">Barcode detectado</span>
              <span className="rt-val mono">{result.barcode ?? '—'}</span>
            </div>
            <div className="rt-field">
              <span className="rt-label">Objeto detectado</span>
              <span className={`rt-val ${result.detected ? 'text-cyan' : 'text-dim'}`}>
                {result.detected ? 'Sim' : 'Não'}
              </span>
            </div>
            <div className="rt-field">
              <span className="rt-label">Confiança</span>
              <div className="confidence-bar-wrap">
                <div
                  className="confidence-bar"
                  style={{ width: `${Math.round(result.detection_confidence * 100)}%` }}
                />
                <span className="confidence-val mono">
                  {Math.round(result.detection_confidence * 100)}%
                </span>
              </div>
            </div>
          </div>

          <div className="result-checks">
            <div className={`check-item ${result.barcode_ok ? 'check-ok' : 'check-fail'}`}>
              <span className="check-icon">{result.barcode_ok ? '✓' : '✗'}</span>
              <span>Barcode</span>
            </div>
            <div className={`check-item ${result.weight_ok ? 'check-ok' : 'check-fail'}`}>
              <span className="check-icon">{result.weight_ok ? '✓' : '✗'}</span>
              <span>Peso</span>
            </div>
          </div>

          {result.reason && (
            <p className="result-reason">
              <span className="result-reason-label">Motivo:</span> {result.reason}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
