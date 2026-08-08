from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # env vars do OS têm prioridade sobre .env por padrão no pydantic-settings
    )

    # Application
    app_name: str = "Inspection AI"
    app_version: str = "0.1.0"
    debug: bool = False

    # Ambiente de execução — controla CORS, /docs, comportamento de segurança
    # Valores válidos: "dev" | "prod"
    # Em "dev": CORS aberto (["*"]), /docs habilitado
    # Em "prod": CORS restrito a allowed_origins, /docs desabilitado
    environment: str = "dev"

    # CORS — origens permitidas em ambiente de produção
    # Em dev, ignored (["*"] é usado automaticamente)
    # Em prod, configurar com os domínios reais do frontend
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    # Database — lida de DATABASE_URL injetada pelo docker-compose
    database_url: str = "postgresql://inspection_user:inspection_password@localhost:5432/inspection_ai"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Camera — controla qual fonte de frames o VisionWorker usa.
    # Valores válidos: "simulated" (padrão, sem hardware) | "webcam" (câmera física via OpenCV)
    # Se CAMERA_MODE=webcam e a câmera não estiver disponível, o sistema faz
    # fallback automático para "simulated" sem derrubar o backend.
    camera_mode: str = "simulated"
    camera_index: int = 0          # índice do dispositivo (0 = câmera padrão do SO)
    camera_fps: float = 5.0        # FPS alvo em modo webcam

    # Sprint 10C.2 — código da linha usada como "linha padrão" (reutiliza
    # o event_bus singleton e responde no alias WS de compatibilidade
    # /ws/inspection). Deve bater com o code criado pela migration 0007.
    default_line_code: str = "L01"

    # Storage — caminho base para imagens capturadas pela esteira
    # Em Docker: /app/storage (volume montado em docker-compose.yml)
    # Em dev local: ./storage (relativo ao CWD do processo)
    storage_path: str = "/app/storage"

    # YOLO — inferência real via YOLOv8 (Sprint 8A)
    # yolo_enabled=False por padrão: sistema funciona sem ultralytics instalado.
    # Para ativar: YOLO_ENABLED=true + modelo em yolo_model_path.
    yolo_enabled: bool = False
    yolo_model_path: str = "vision/models/yolov8n.pt"
    yolo_confidence_min: float = 0.50

    # ── Sprint 9B.1 — Autenticação JWT ──────────────────────────────────────
    # JWT_SECRET_KEY: chave secreta para assinar tokens.
    # Em produção: gerar com `openssl rand -hex 32` e injetar via variável de ambiente.
    # O default abaixo é APENAS para desenvolvimento local — NUNCA usar em produção.
    jwt_secret_key: str = "dev-secret-key-change-in-production-use-openssl-rand-hex-32"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60       # 1 hora
    jwt_refresh_token_expire_minutes: int = 10080   # 7 dias

    # ── Sprint 9B.2 — Database Connection Pool ───────────────────────────────
    # pool_size     : conexões permanentes mantidas abertas no pool.
    #                 Regra prática: (núcleos_da_CPU × 2) + disco_efetivo
    #                 Default conservador para PC industrial com 4 cores.
    # max_overflow  : conexões extras criadas quando pool_size está esgotado.
    #                 Total máximo simultâneo = pool_size + max_overflow.
    # pool_timeout  : segundos de espera por uma conexão antes de TimeoutError.
    #                 30s é razoável; reduzir em sistemas de alta carga.
    # pool_recycle  : tempo (segundos) antes de reciclar uma conexão do pool.
    #                 Evita "server closed the connection unexpectedly" após idle longo.
    #                 1800s = 30 minutos — menor que qualquer timeout de firewall industrial.
    # pool_pre_ping : executa "SELECT 1" antes de usar conexão do pool.
    #                 Detecta conexões mortas antes de falhar na query real.
    db_pool_size:     int   = 10
    db_max_overflow:  int   = 20
    db_pool_timeout:  float = 30.0
    db_pool_recycle:  int   = 1800

    # ── Sprint 9B.2 — WebSocket Heartbeat ───────────────────────────────────
    # ws_heartbeat_interval : segundos entre pings de status ao cliente.
    #                         30s é conservador; firewalls industriais costumam
    #                         ter idle timeout de 60–300s.
    # ws_send_timeout       : segundos máximos para completar um send_json.
    #                         Se excedido, conexão é considerada morta e removida.
    #                         Evita corrotinas bloqueadas por conexões TCP zumbi.
    ws_heartbeat_interval: int   = 30
    ws_send_timeout:       float = 10.0

    # ── Sprint 9B.3 — Circuit Breaker ────────────────────────────────────────
    # Aplicado em dois pontos críticos:
    #   1. VisionWorker._run() → protege contra falhas repetidas do detector
    #   2. EventBus._persist_safe() → protege contra banco offline
    #
    # cb_failure_threshold : falhas consecutivas para abrir o circuito (OPEN)
    # cb_reset_timeout     : segundos em OPEN antes de tentar HALF_OPEN
    #
    # Comportamento:
    #   CLOSED    → operação normal; conta falhas consecutivas
    #   OPEN      → após N falhas: bloqueia chamadas, aguarda reset_timeout
    #   HALF_OPEN → permite 1 tentativa; sucesso→CLOSED, falha→OPEN
    #
    # Valores conservadores para ambiente industrial:
    #   5 falhas  → OPEN (evita log spam; 1s a 5fps antes de silenciar)
    #   30s reset → HALF_OPEN (tempo suficiente para banco reiniciar)
    cb_failure_threshold: int   = 5
    cb_reset_timeout:     float = 30.0

    # ── Sprint 9B.4 — Observabilidade ────────────────────────────────────────

    # Health check
    # health_timeout_seconds : timeout máximo para cada verificação de dependência.
    #   Garante que /health responde em tempo finito mesmo com banco lento.
    health_timeout_seconds: float = 5.0

    # Prometheus
    # prometheus_enabled : habilita endpoint GET /metrics em formato Prometheus.
    #   Em produção: expor apenas para rede interna (Prometheus scraper).
    #   Em dev: habilitado por padrão para facilitar inspeção local.
    prometheus_enabled: bool = True

    # Storage / Disco
    # disk_warning_percent  : alerta no /health quando disco > N% cheio.
    # disk_critical_percent : /health retorna "degraded" quando disco > N% cheio.
    disk_warning_percent:  float = 80.0
    disk_critical_percent: float = 95.0

    # Retenção de imagens (LGPD / Sprint 9B.4 Fase 3)
    # image_retention_days : imagens mais antigas que N dias são elegíveis para exclusão.
    #   0 = nunca deletar automaticamente (útil em ambientes de auditoria)
    # image_cleanup_enabled : se False, nenhuma imagem é deletada automaticamente.
    #   Pode ser desabilitado por regulação ou contrato de qualidade.
    # image_cleanup_hour    : hora UTC (0–23) de execução do cleanup diário.
    #   2 = 2h UTC (madrugada na maioria dos fusos industriais)
    image_retention_days:  int  = 30
    image_cleanup_enabled: bool = True
    image_cleanup_hour:    int  = 2
    # Se True, detecta arquivos/registros órfãos a cada ciclo de cleanup.
    # Resultados são logados como WARNING para ação manual.
    orphan_check_enabled:  bool = True


settings = Settings()
