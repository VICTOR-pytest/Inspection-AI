import { useState } from 'react'
import { api } from '../services/api'
import type { InspectionResult } from '../types/inspection'

export function useManualInspection() {
  const [barcode, setBarcode] = useState('')
  const [weight, setWeight] = useState('')
  const [result, setResult] = useState<InspectionResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!barcode.trim() || !weight) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await api.checkInspection({
        barcode: barcode.trim(),
        weight: parseFloat(weight),
      })
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro desconhecido')
    } finally {
      setLoading(false)
    }
  }

  function reset() {
    setBarcode('')
    setWeight('')
    setResult(null)
    setError(null)
  }

  return { barcode, setBarcode, weight, setWeight, result, loading, error, submit, reset }
}
