import { useState } from 'react'
import type { AuthHook } from '../hooks/useAuth'

interface LoginPageProps {
  auth: AuthHook
}

export function LoginPage({ auth }: LoginPageProps) {
  const [email,    setEmail]    = useState('')
  const [password, setPassword] = useState('')
  const [error,    setError]    = useState<string | null>(null)
  const [loading,  setLoading]  = useState(false)

  async function handleSubmit() {
    if (!email.trim() || !password.trim()) {
      setError('Preencha e-mail e senha.')
      return
    }
    setError(null)
    setLoading(true)
    try {
      await auth.login(email.trim(), password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha no login.')
    } finally {
      setLoading(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') handleSubmit()
  }

  return (
    <div className="login-backdrop">
      <div className="login-card">
        <div className="login-logo">
          <span className="login-logo-icon">⬡</span>
          <span className="login-logo-text">Inspection AI</span>
        </div>

        <p className="login-subtitle">Sistema de inspeção visual industrial</p>

        <div className="login-field">
          <label className="login-label" htmlFor="email">E-mail</label>
          <input
            id="email"
            className="login-input"
            type="email"
            autoComplete="username"
            placeholder="operador@empresa.com"
            value={email}
            onChange={e => setEmail(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
          />
        </div>

        <div className="login-field">
          <label className="login-label" htmlFor="password">Senha</label>
          <input
            id="password"
            className="login-input"
            type="password"
            autoComplete="current-password"
            placeholder="••••••••"
            value={password}
            onChange={e => setPassword(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
          />
        </div>

        {error && (
          <div className="login-error" role="alert">
            {error}
          </div>
        )}

        <button
          className="login-btn"
          onClick={handleSubmit}
          disabled={loading}
        >
          {loading ? 'Entrando…' : 'Entrar'}
        </button>
      </div>
    </div>
  )
}
