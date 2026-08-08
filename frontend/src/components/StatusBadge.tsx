interface StatusBadgeProps {
  valid: boolean
  size?: 'sm' | 'lg'
}

export function StatusBadge({ valid, size = 'sm' }: StatusBadgeProps) {
  return (
    <span
      className={`status-badge ${valid ? 'status-approved' : 'status-rejected'} ${size === 'lg' ? 'status-badge--lg' : ''}`}
    >
      <span className="status-dot" />
      {valid ? 'APROVADO' : 'REJEITADO'}
    </span>
  )
}
