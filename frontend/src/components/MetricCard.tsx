/**
 * MetricCard.tsx — Sprint 6
 * Card reutilizável de métrica (usado no Dashboard operacional).
 */
interface Props {
  label: string
  value: string | number
  accent?: 'cyan' | 'green' | 'red' | 'orange' | 'neutral'
  sub?: string
}

const accentVar: Record<NonNullable<Props['accent']>, string> = {
  cyan:    'var(--cyan)',
  green:   'var(--green)',
  red:     'var(--red)',
  orange:  'var(--orange)',
  neutral: 'var(--text)',
}

export function MetricCard({ label, value, accent = 'neutral', sub }: Props) {
  return (
    <div className="metric-card-s6">
      <span className="metric-card-s6-value" style={{ color: accentVar[accent] }}>
        {value}
      </span>
      <span className="metric-card-s6-label">{label}</span>
      {sub && <span className="metric-card-s6-sub">{sub}</span>}
    </div>
  )
}
