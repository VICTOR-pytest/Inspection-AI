import { useCallback, useRef, useState } from 'react'
import type { AuthState, UserInfo } from '../types/auth'

const SESSION_KEY_TOKEN   = 'inspection_ai_token'
const SESSION_KEY_REFRESH = 'inspection_ai_refresh'
const SESSION_KEY_USER    = 'inspection_ai_user'

function loadFromSession(): Pick<AuthState, 'token' | 'refreshToken' | 'user'> {
  try {
    return {
      token:        sessionStorage.getItem(SESSION_KEY_TOKEN),
      refreshToken: sessionStorage.getItem(SESSION_KEY_REFRESH),
      user:         JSON.parse(sessionStorage.getItem(SESSION_KEY_USER) ?? 'null'),
    }
  } catch {
    return { token: null, refreshToken: null, user: null }
  }
}

function saveToSession(token: string, refreshToken: string, user: UserInfo) {
  sessionStorage.setItem(SESSION_KEY_TOKEN,   token)
  sessionStorage.setItem(SESSION_KEY_REFRESH, refreshToken)
  sessionStorage.setItem(SESSION_KEY_USER,    JSON.stringify(user))
}

function clearSession() {
  sessionStorage.removeItem(SESSION_KEY_TOKEN)
  sessionStorage.removeItem(SESSION_KEY_REFRESH)
  sessionStorage.removeItem(SESSION_KEY_USER)
}

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export function useAuth() {
  const saved = loadFromSession()
  const [state, setState] = useState<AuthState>({
    token:           saved.token,
    refreshToken:    saved.refreshToken,
    user:            saved.user,
    isAuthenticated: saved.token !== null,
  })

  const refreshingRef = useRef(false)

  const login = useCallback(async (email: string, password: string): Promise<void> => {
    const res = await fetch(`${BASE_URL}/auth/login`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ email, password }),
    })

    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body?.detail ?? `Erro ${res.status}`)
    }

    const tokens = await res.json()

    const meRes = await fetch(`${BASE_URL}/auth/me`, {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
    })
    if (!meRes.ok) throw new Error('Não foi possível carregar os dados do usuário.')
    const user: UserInfo = await meRes.json()

    saveToSession(tokens.access_token, tokens.refresh_token, user)
    setState({
      token:           tokens.access_token,
      refreshToken:    tokens.refresh_token,
      user,
      isAuthenticated: true,
    })
  }, [])

  const logout = useCallback(() => {
    clearSession()
    setState({ token: null, refreshToken: null, user: null, isAuthenticated: false })
  }, [])

  const refresh = useCallback(async (): Promise<string | null> => {
    if (refreshingRef.current) return state.token
    const currentRefresh = state.refreshToken
    if (!currentRefresh) { logout(); return null }

    refreshingRef.current = true
    try {
      const res = await fetch(`${BASE_URL}/auth/refresh`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ refresh_token: currentRefresh }),
      })
      if (!res.ok) { logout(); return null }

      const tokens = await res.json()
      const user = state.user!
      saveToSession(tokens.access_token, tokens.refresh_token, user)
      setState(prev => ({
        ...prev,
        token:        tokens.access_token,
        refreshToken: tokens.refresh_token,
      }))
      return tokens.access_token as string
    } catch {
      logout()
      return null
    } finally {
      refreshingRef.current = false
    }
  }, [state.refreshToken, state.token, state.user, logout])

  const getToken = useCallback(() => state.token, [state.token])

  return { ...state, login, logout, refresh, getToken }
}

export type AuthHook = ReturnType<typeof useAuth>
