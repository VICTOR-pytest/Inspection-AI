"""
app/core/circuit_breaker.py
----------------------------
Sprint 9B.3 — Implementação do padrão Circuit Breaker.

Aplicado em dois pontos críticos do sistema:
  1. VisionWorker._run()       → protege detector.detect() contra falhas repetidas
  2. EventBus._persist_safe()  → protege persistência contra banco offline

Motivação:
  Sem circuit breaker, falhas repetidas causam:
    - Log spam: 5 erros/segundo a 5fps quando banco está offline
    - Pool de conexões esgotado: cada tentativa consome uma conexão
    - Diagnóstico difícil: log inundado, sinal real perdido no ruído
    - Sem recuperação automática: operador precisa reiniciar manualmente

  Com circuit breaker:
    - 5 falhas consecutivas → OPEN: para de tentar, log de abertura
    - Silêncio por 30s → HALF_OPEN: 1 tentativa de prova
    - Sucesso → CLOSED: retoma operação normal, log de fechamento
    - Falha no HALF_OPEN → OPEN: reinicia timer de 30s

Estados:
  CLOSED    → operação normal, conta falhas consecutivas
  OPEN      → bloqueado, aguarda reset_timeout antes de tentar HALF_OPEN
  HALF_OPEN → permite UMA tentativa; sucesso → CLOSED, falha → OPEN

Uso:
  cb = CircuitBreaker(name="detector", failure_threshold=5, reset_timeout=30.0)

  # Síncrono (VisionWorker thread):
  if cb.can_attempt():
      try:
          result = risky_operation()
          cb.record_success()
      except Exception as exc:
          cb.record_failure(exc)

  # Assíncrono (EventBus coroutine):
  if cb.can_attempt():
      try:
          await risky_coroutine()
          cb.record_success()
      except Exception as exc:
          cb.record_failure(exc)
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from threading import Lock

log = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED    = "CLOSED"     # operação normal
    OPEN      = "OPEN"       # bloqueado — aguardando reset_timeout
    HALF_OPEN = "HALF_OPEN"  # testando — permite 1 tentativa


class CircuitBreaker:
    """
    Circuit breaker thread-safe e asyncio-safe.

    Thread-safety: usa threading.Lock para proteger estado interno.
    Pode ser usado tanto em threads (VisionWorker) quanto em corrotinas
    (EventBus) sem risco de race condition — operações são atômicas.

    Parameters
    ----------
    name : str
        Identificador para logs (ex: "detector", "persistence").
    failure_threshold : int
        Número de falhas consecutivas para abrir o circuito.
    reset_timeout : float
        Segundos em estado OPEN antes de tentar HALF_OPEN.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
    ) -> None:
        self.name              = name
        self.failure_threshold = failure_threshold
        self.reset_timeout     = reset_timeout

        self._state: CircuitState     = CircuitState.CLOSED
        self._failure_count: int      = 0
        self._last_failure_time: float = 0.0
        self._lock                    = Lock()

    # ── Propriedades públicas (thread-safe) ───────────────────────────────

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._get_state_locked()

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED

    # ── Interface principal ───────────────────────────────────────────────

    def can_attempt(self) -> bool:
        """
        Retorna True se a operação deve ser tentada.

        CLOSED    → True  (operação normal)
        OPEN      → False (bloqueado) — exceto se reset_timeout expirou
        HALF_OPEN → True  (1 tentativa de prova permitida)

        Esta é a única verificação necessária antes de cada operação.
        """
        with self._lock:
            state = self._get_state_locked()
            return state != CircuitState.OPEN

    def record_success(self) -> None:
        """
        Registra execução bem-sucedida.

        Em qualquer estado:
          - Zera contador de falhas
          - Transita para CLOSED

        Especialmente importante em HALF_OPEN: indica que o recurso
        se recuperou e o circuito pode ser fechado novamente.
        """
        with self._lock:
            prev_state = self._state
            self._failure_count    = 0
            self._last_failure_time = 0.0
            self._state            = CircuitState.CLOSED

        if prev_state != CircuitState.CLOSED:
            log.info(
                "CircuitBreaker[%s]: %s → CLOSED após sucesso",
                self.name,
                prev_state.value,
            )

    def record_failure(self, exc: Exception | None = None) -> None:
        """
        Registra falha na operação.

        CLOSED: incrementa contador; se atingir threshold → OPEN
        HALF_OPEN: tentativa de prova falhou → OPEN (reinicia timer)
        OPEN: não deveria ser chamado (can_attempt() retorna False),
              mas se for chamado, apenas atualiza o timer.
        """
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            prev_state = self._state

            if self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    log.warning(
                        "CircuitBreaker[%s]: CLOSED → OPEN "
                        "após %d falhas consecutivas. "
                        "Próxima tentativa em %.0fs. Última falha: %s",
                        self.name,
                        self._failure_count,
                        self.reset_timeout,
                        exc,
                    )
            elif self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                log.warning(
                    "CircuitBreaker[%s]: HALF_OPEN → OPEN "
                    "após falha na tentativa de prova. "
                    "Próxima tentativa em %.0fs. Falha: %s",
                    self.name,
                    self.reset_timeout,
                    exc,
                )
            # OPEN: apenas atualiza timer (já logado na transição)

    def reset(self) -> None:
        """
        Força reset para CLOSED (para uso em testes e reinicialização manual).
        """
        with self._lock:
            self._state             = CircuitState.CLOSED
            self._failure_count     = 0
            self._last_failure_time = 0.0
        log.info("CircuitBreaker[%s]: reset forçado para CLOSED", self.name)

    def get_status(self) -> dict:
        """
        Retorna snapshot do estado atual para métricas e health check.

        Retorna dict com:
          state           : "CLOSED" | "OPEN" | "HALF_OPEN"
          failure_count   : falhas consecutivas acumuladas
          time_until_retry: segundos restantes até HALF_OPEN (0 se não OPEN)
        """
        with self._lock:
            state = self._get_state_locked()
            time_until_retry = 0.0
            if state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_failure_time
                time_until_retry = max(0.0, self.reset_timeout - elapsed)
            return {
                "name":             self.name,
                "state":            state.value,
                "failure_count":    self._failure_count,
                "time_until_retry": round(time_until_retry, 1),
            }

    # ── Interno ───────────────────────────────────────────────────────────

    def _get_state_locked(self) -> CircuitState:
        """
        Retorna o estado atual com transição automática OPEN → HALF_OPEN.

        Deve ser chamado com self._lock já adquirido.
        """
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.reset_timeout:
                self._state = CircuitState.HALF_OPEN
                log.info(
                    "CircuitBreaker[%s]: OPEN → HALF_OPEN "
                    "após %.0fs. Testando recuperação...",
                    self.name,
                    elapsed,
                )
        return self._state

    def __repr__(self) -> str:
        return (
            f"<CircuitBreaker name={self.name!r} "
            f"state={self._state.value} "
            f"failures={self._failure_count}>"
        )
