"""
app/api/v1/ws.py
----------------
WebSocket endpoint — Sprint 5 + autenticação Sprint 9B.1 + heartbeat Sprint 9B.2.
Sprint 10C.2 (PR-005) — WebSocket por linha.

GET /ws/inspection/{line_id}?token=<jwt>   — canal da linha específica
GET /ws/inspection?token=<jwt>             — alias de compatibilidade,
                                              resolve para a linha padrão
                                              (settings.default_line_code,
                                              "L01" por padrão)

Fluxo de conexão:
  1. Extrai token do query param ?token=<jwt>
  2. Valida JWT antes de websocket.accept()
  3. Se inválido: fecha com código 4001 SEM consumir recursos do EventBus
  4. Resolve o EventBus da linha (via LineRegistry; alias usa a linha
     default) — se a linha não existir/estiver em runtime, fecha com 4004
  5. Se válido: accept() → register no EventBus DAQUELA linha → heartbeat

Isolamento (PR-005): cada cliente só recebe eventos publicados no bus da
própria linha — nunca eventos de outras linhas, pois cada EventBus tem
sua própria lista de clientes registrados (ver app/core/events.py).

Sprint 9B.2 — Heartbeat real:
  Problema anterior: o loop fazia asyncio.sleep(N) + send_json().
  Isso é um push de dados, não um heartbeat de protocolo. Conexões TCP
  mortas silenciosamente (firewall industrial, cabo desconectado) não eram
  detectadas — a corrotina ficava bloqueada no send por até 20 minutos.

  Solução implementada:
  - asyncio.wait_for(send_json(), timeout=ws_send_timeout) em CADA send
  - Se o send exceder ws_send_timeout segundos: conexão considerada morta,
    removida do EventBus imediatamente sem aguardar o TCP timeout do OS
  - ws_heartbeat_interval e ws_send_timeout configuráveis via Settings/env vars

  Resultado: conexão zumbi detectada e removida em no máximo
  ws_heartbeat_interval + ws_send_timeout segundos (default: 30 + 10 = 40s).
  Antes: podia levar até 20 minutos (TCP_USER_TIMEOUT padrão do Linux).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.events import EventBus, event_bus
from app.core.security import decode_websocket_token
from app.database.session import SessionLocal

log = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

# RFC 6455 — códigos 4000-4999 são reservados para uso de aplicação
_WS_CLOSE_UNAUTHORIZED = 4001
_WS_CLOSE_LINE_NOT_FOUND = 4004  # Sprint 10C.2


async def _send_with_timeout(websocket: WebSocket, payload: dict) -> None:
    """
    Envia JSON com timeout configurável.

    Levanta asyncio.TimeoutError se o send não completar em
    settings.ws_send_timeout segundos. Permite detecção rápida de
    conexões TCP mortas sem aguardar o timeout do sistema operacional.
    """
    await asyncio.wait_for(
        websocket.send_json(payload),
        timeout=settings.ws_send_timeout,
    )


def _resolve_bus_for_default_line() -> EventBus:
    """
    Sprint 10C.2 — resolve o EventBus da linha padrão.

    Se o LineRegistry já tiver sido populado (modo multi-linha ativo no
    lifespan), usa o bus registrado para a linha default — que, por
    construção (ver app/main.py::_bootstrap_line_registry), É o mesmo
    `event_bus` singleton quando só existe a linha padrão. Se o registry
    estiver vazio (modo fallback legado, ou testes que não passam pelo
    lifespan real), cai direto no singleton — comportamento idêntico ao
    pré-10C.2.
    """
    try:
        from app.core.line_registry import line_registry
        ctx = line_registry.default()
        if ctx is not None and ctx.event_bus is not None:
            return ctx.event_bus
    except Exception:
        pass
    return event_bus


def _resolve_bus_for_line(line_id: int) -> EventBus | None:
    """Sprint 10C.2 — resolve o EventBus de uma linha específica pelo id."""
    try:
        from app.core.line_registry import line_registry
        ctx = line_registry.get(line_id)
        if ctx is not None and ctx.event_bus is not None:
            return ctx.event_bus
    except Exception:
        pass
    return None


async def _ws_inspection_impl(
    websocket: WebSocket,
    bus: EventBus,
    line_label: str,
) -> None:
    """
    Implementação compartilhada entre a rota por linha e o alias legado.

    `line_label` é usado apenas em logs, para diferenciar a origem da
    conexão nos registros (ex: "line_id=2" ou "default").
    """
    # ── 1. Validar token ANTES de accept() ────────────────────────────────
    token: str = websocket.query_params.get("token", "")

    db = SessionLocal()
    try:
        user = decode_websocket_token(token, db)
    except Exception as exc:
        log.warning(
            "WS rejeitado (token inválido): %s | client=%s | %s",
            exc,
            websocket.client,
            line_label,
        )
        await websocket.close(code=_WS_CLOSE_UNAUTHORIZED)
        return
    finally:
        db.close()

    # ── 2. Aceitar e registrar no EventBus da linha ───────────────────────
    await websocket.accept()
    bus.register(websocket)
    log.info(
        "WS conectado: user_id=%d role=%s clients=%d %s",
        user.id,
        user.role,
        bus.client_count,
        line_label,
    )

    # ── 3. Snapshot inicial ───────────────────────────────────────────────
    try:
        await _send_with_timeout(websocket, bus.status_snapshot())
    except (asyncio.TimeoutError, Exception) as exc:
        log.warning(
            "WS snapshot inicial falhou (user_id=%d, %s): %s — encerrando",
            user.id,
            line_label,
            exc,
        )
        bus.unregister(websocket)
        return

    # ── 4. Loop de heartbeat com timeout por send ─────────────────────────
    try:
        while True:
            await asyncio.sleep(settings.ws_heartbeat_interval)
            await _send_with_timeout(websocket, bus.status_snapshot())

    except asyncio.TimeoutError:
        log.warning(
            "WS timeout de send (user_id=%d, timeout=%.1fs, %s) — conexão removida",
            user.id,
            settings.ws_send_timeout,
            line_label,
        )
    except WebSocketDisconnect:
        log.info("WS desconectado normalmente: user_id=%d %s", user.id, line_label)
    except Exception as exc:
        log.warning("WS erro inesperado: user_id=%d %s error=%s", user.id, line_label, exc)
    finally:
        bus.unregister(websocket)
        log.info(
            "WS encerrado: user_id=%d clients_restantes=%d %s",
            user.id,
            bus.client_count,
            line_label,
        )


@router.websocket("/ws/inspection/{line_id}")
async def ws_inspection_by_line(websocket: WebSocket, line_id: int) -> None:
    """
    Sprint 10C.2 (PR-005) — canal WebSocket dedicado a uma linha de
    produção. Cliente recebe SOMENTE eventos publicados nessa linha.
    """
    bus = _resolve_bus_for_line(line_id)
    if bus is None:
        log.warning("WS rejeitado: linha id=%d não encontrada/ativa em runtime", line_id)
        await websocket.close(code=_WS_CLOSE_LINE_NOT_FOUND)
        return
    await _ws_inspection_impl(websocket, bus, line_label=f"line_id={line_id}")


@router.websocket("/ws/inspection")
async def ws_inspection_default(websocket: WebSocket) -> None:
    """
    Alias de compatibilidade retroativa (Sprint 10C.2). Resolve
    automaticamente para a linha padrão — nenhuma alteração é exigida do
    frontend/clientes existentes que já usam esta rota sem `line_id`.
    """
    bus = _resolve_bus_for_default_line()
    await _ws_inspection_impl(websocket, bus, line_label="default")
