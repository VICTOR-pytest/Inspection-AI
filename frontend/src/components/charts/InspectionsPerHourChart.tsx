/**
 * InspectionsPerHourChart.tsx — Sprint 6
 * Gráfico de linha: total de inspeções por hora (últimas 24h).
 */
import {
  CartesianGrid, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import type { HourlyBucket } from '../../types/dashboard'

function formatHour(iso: string): string {
  return new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
}

export function InspectionsPerHourChart({ data }: { data: HourlyBucket[] }) {
  const chartData = data.map(b => ({ ...b, label: formatHour(b.hour) }))

  if (chartData.length === 0) {
    return <div className="chart-empty">Sem dados nas últimas 24h.</div>
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={chartData} margin={{ top: 8, right: 16, left: -16, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#21262D" />
        <XAxis dataKey="label" stroke="#7D8590" fontSize={11} tickLine={false} />
        <YAxis stroke="#7D8590" fontSize={11} tickLine={false} allowDecimals={false} />
        <Tooltip
          contentStyle={{
            background: '#161B22', border: '1px solid #30363D',
            borderRadius: 8, fontSize: 12, color: '#E6EDF3',
          }}
          labelStyle={{ color: '#7D8590' }}
        />
        <Line
          type="monotone" dataKey="total" name="Total"
          stroke="#00D4FF" strokeWidth={2} dot={false}
          activeDot={{ r: 4 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
