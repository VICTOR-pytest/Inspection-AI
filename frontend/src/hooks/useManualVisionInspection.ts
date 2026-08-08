/**
 * useManualVisionInspection.ts
 * Hook para inspeção manual via HTTP POST (aba "Realtime Vision").
 * NÃO é o hook de streaming WebSocket — para isso use useWebSocketInspection.
 */
import { useState } from 'react'
import { api } from '../services/api'
import type { RealtimeInspectionResult } from '../types/inspection'

// Produto seed A: barcode 789123456, peso esperado 1.00 ±5%
// Produto seed B: barcode 111222333, peso esperado 0.500 ±10%
export const REALTIME_PRESETS = [
  { label: 'Produto A — Aprovado', barcode: '789123456', weight: 1.02 },
  { label: 'Produto A — Peso baixo', barcode: '789123456', weight: 0.80 },
  { label: 'Produto B — Aprovado', barcode: '111222333', weight: 0.50 },
  { label: 'Barcode inválido', barcode: 'INVALID999', weight: 0.99 },
  { label: 'Sem detecção (dummy)', barcode: '', weight: 1.00 },
]

// Base64 mínima de imagem 1×1 pixel PNG transparente (válida para o backend)
const DUMMY_IMAGE_BASE64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='

export function useManualVisionInspection() {
  const [presetIndex, setPresetIndex] = useState(0)
  const [customWeight, setCustomWeight] = useState('')
  const [result, setResult] = useState<RealtimeInspectionResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const preset = REALTIME_PRESETS[presetIndex]

  async function simulate() {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const weight = customWeight ? parseFloat(customWeight) : preset.weight
      const res = await api.realtimeInspection({
        image: DUMMY_IMAGE_BASE64,
        weight,
      })
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro desconhecido')
    } finally {
      setLoading(false)
    }
  }

  function reset() {
    setResult(null)
    setError(null)
    setCustomWeight('')
  }

  return {
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
  }
}
