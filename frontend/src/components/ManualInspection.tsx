import { useManualInspection } from '../hooks/useManualInspection'
import { StatusBadge } from './StatusBadge'

export function ManualInspection() {
  const { barcode, setBarcode, weight, setWeight, result, loading, error, submit, reset } =
    useManualInspection()

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-icon panel-icon--blue">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
          </svg>
        </div>
        <div>
          <h2 className="panel-title">Inspeção Manual</h2>
          <p className="panel-subtitle">Validação por barcode + peso</p>
        </div>
      </div>

      <div className="form-grid">
        <div className="field">
          <label className="field-label">Código de Barras</label>
          <input
            className="field-input"
            type="text"
            placeholder="Ex: 789123456"
            value={barcode}
            onChange={(e) => setBarcode(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
          />
        </div>
        <div className="field">
          <label className="field-label">Peso (kg)</label>
          <input
            className="field-input"
            type="number"
            step="0.01"
            min="0"
            placeholder="Ex: 1.02"
            value={weight}
            onChange={(e) => setWeight(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
          />
        </div>
      </div>

      <div className="button-row">
        <button
          className="btn btn--primary"
          onClick={submit}
          disabled={loading || !barcode.trim() || !weight}
        >
          {loading ? <span className="spinner" /> : null}
          {loading ? 'Validando…' : 'Inspecionar'}
        </button>
        {result && (
          <button className="btn btn--ghost" onClick={reset}>
            Limpar
          </button>
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
