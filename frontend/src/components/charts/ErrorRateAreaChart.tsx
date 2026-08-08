/**
 * ErrorRateAreaChart.tsx — Sprint 6
 * Gráfico de área: taxa de erro (%) por hora.
 */
import {
  Area, AreaChart, CartesianGrid,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import type { HourlyBucket } from '../../types/dashboard'

function formatHour(iso: string): string {
  return new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
}

export function ErrorRateAreaChart({ data }: { data: HourlyBucket[] }) {
  const chartData = data.map(b => ({
    ...b,
    label: formatHour(b.hour),
    errorRate: b.total > 0 ? Math.round((b.rejected / b.total) * 1000) / 10 : 0,
  }))

  if (chartData.length === 0) {
    return <div className="chart-empty">Sem dados nas últimas 24h.</div>
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={chartData} margin={{ top: 8, right: 16, left: -16, bottom: 0 }}>
        <defs>
          <linearGradient id="errorRateGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#FF6B35" stopOpacity={0.4} />
            <stop offset="95%" stopColor="#FF6B35" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#21262D" />
        <XAxis dataKey="label" stroke="#7D8590" fontSize={11} tickLine={false} />
        <YAxis
          stroke="#7D8590" fontSize={11} tickLine={false}
          unit="%" domain={[0, 100]}
        />
        <Tooltip
          contentStyle={{
            background: '#161B22', border: '1px solid #30363D',
            borderRadius: 8, fontSize: 12, color: '#E6EDF3',
          }}
          labelStyle={{ color: '#7D8590' }}
          formatter={(value: number) => [`${value}%`, 'Taxa de erro']}
        />
        <Area
          type="monotone" dataKey="errorRate"
          stroke="#FF6B35" strokeWidth={2}
          fill="url(#errorRateGradient)"
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
