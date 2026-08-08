import { useEffect } from 'react'
import { ManualInspection } from './components/ManualInspection'
import { RealtimeSimulation } from './components/RealtimeSimulation'
import { LiveDashboard } from './components/LiveDashboard'
import { Dashboard } from './pages/Dashboard'
import { Inspections } from './pages/Inspections'
import { LoginPage } from './pages/LoginPage'
import { useAuth } from './hooks/useAuth'
import { configureAuth } from './services/api'
import { useState } from 'react'
import './App.css'

type Tab = 'dashboard' | 'live' | 'manual' | 'realtime' | 'history'

export default function App() {
  const auth = useAuth()
  const [tab, setTab] = useState<Tab>('dashboard')

  useEffect(() => {
    configureAuth(
      () => auth.token,
      () => auth.logout(),
    )
  }, [auth.token, auth.logout])

  if (!auth.isAuthenticated) {
    return <LoginPage auth={auth} />
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header-inner">
          <div className="app-logo">
            <div className="logo-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" strokeWidth="2">
                <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </div>
            <div>
              <span className="logo-name">Inspection AI</span>
              <span className="logo-tag">PAINEL INDUSTRIAL</span>
            </div>
          </div>

          <div className="app-header-right">
            <div className="app-status">
              <span className="status-live-dot" />
              <span className="status-live-text">SISTEMA ONLINE</span>
            </div>

            <div className="user-badge">
              <span className="user-badge-role">{auth.user?.role}</span>
              <span className="user-badge-name">{auth.user?.full_name}</span>
              <button
                className="logout-btn"
                onClick={auth.logout}
                title="Sair do sistema"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" strokeWidth="2">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                  <polyline points="16 17 21 12 16 7" />
                  <line x1="21" y1="12" x2="9" y2="12" />
                </svg>
                Sair
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="app-main">
        <nav className="tab-nav">
          <button
            className={`tab-btn ${tab === 'dashboard' ? 'tab-btn--active' : ''}`}
            onClick={() => setTab('dashboard')}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="7" height="9" />
              <rect x="14" y="3" width="7" height="5" />
              <rect x="14" y="12" width="7" height="9" />
              <rect x="3" y="16" width="7" height="5" />
            </svg>
            Dashboard
          </button>
          <button
            className={`tab-btn ${tab === 'live' ? 'tab-btn--active' : ''}`}
            onClick={() => setTab('live')}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2">
              <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
            </svg>
            Live WS
          </button>
          <button
            className={`tab-btn ${tab === 'manual' ? 'tab-btn--active' : ''}`}
            onClick={() => setTab('manual')}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2">
              <path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
            </svg>
            Inspeção Manual
          </button>
          <button
            className={`tab-btn ${tab === 'realtime' ? 'tab-btn--active' : ''}`}
            onClick={() => setTab('realtime')}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="3" />
              <path d="M3 12h1M20 12h1M12 3v1M12 20v1" />
            </svg>
            Realtime Vision
          </button>
          <button
            className={`tab-btn ${tab === 'history' ? 'tab-btn--active' : ''}`}
            onClick={() => setTab('history')}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
            Histórico
          </button>
        </nav>

        <div className="tab-content">
          {tab === 'dashboard' && <Dashboard />}
          {tab === 'live'      && <LiveDashboard getToken={auth.getToken} />}
          {tab === 'manual'    && <ManualInspection />}
          {tab === 'realtime'  && <RealtimeSimulation />}
          {tab === 'history'   && <Inspections />}
        </div>
      </main>

      <footer className="app-footer">
        <span>Inspection AI</span>
        <span className="footer-sep">·</span>
        <span className="mono text-dim">
          WS: {(import.meta.env.VITE_API_URL ?? 'http://localhost:8000')
            .replace(/^http/, 'ws')}/ws/inspection
        </span>
      </footer>
    </div>
  )
}
