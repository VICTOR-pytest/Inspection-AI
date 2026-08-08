"""
app/repositories/inspection_repository.py
------------------------------------------
Sprint 2:    create, list_recent, get_by_id
Sprint 6:    filtros, paginação, métricas, série horária
Sprint 9A:   update_decision, count_by_decision
Sprint 9B.3: get_aggregate_stats() e hourly_breakdown_sql()

Mudanças Sprint 9B.3:
  get_aggregate_stats(): 6 COUNT() separadas → 1 SELECT com CASE/WHEN (83% menos queries)
  hourly_breakdown_sql(): last_n_hours() O(N) → GROUP BY SQL O(1) memória
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.inspection import Inspection


class InspectionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Sprint 2 ─────────────────────────────────────────────────────────────

    def create(
        self,
        barcode: str,
        weight: float,
        is_valid: bool,
        reason: str | None,
        product_id: int | None,
        confidence: float = 1.0,
        product_name: str | None = None,
        line_id: int | None = None,
        camera_id: int | None = None,
        inspection_run_id: int | None = None,
    ) -> Inspection:
        inspection = Inspection(
            barcode=barcode,
            weight=weight,
            is_valid=is_valid,
            reason=reason,
            product_id=product_id,
            confidence=confidence,
            product_name=product_name,
            created_at=datetime.now(timezone.utc),
            # Sprint 10C.2 — preenchimento automático quando o evento vem
            # de um VisionWorker associado a uma linha (PR-006). Todos
            # nullable — chamadores existentes que não passam esses
            # argumentos continuam funcionando exatamente como antes.
            line_id=line_id,
            camera_id=camera_id,
            inspection_run_id=inspection_run_id,
        )
        self.db.add(inspection)
        self.db.commit()
        self.db.refresh(inspection)
        return inspection

    def list_recent(self, limit: int = 50) -> list[Inspection]:
        return (
            self.db.query(Inspection)
            .order_by(Inspection.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_by_id(self, inspection_id: int) -> Inspection | None:
        return self.db.query(Inspection).filter(Inspection.id == inspection_id).first()

    # ── Sprint 6 — filtros + paginação ───────────────────────────────────────

    def query(
        self,
        barcode: str | None = None,
        valid: bool | None = None,
        product_name: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sort: str = "newest",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Inspection], int]:
        """Retorna (items, total) aplicando filtros + paginação."""
        stmt = select(Inspection)
        count_stmt = select(func.count()).select_from(Inspection)

        conditions = []
        if barcode:
            conditions.append(Inspection.barcode.ilike(f"%{barcode}%"))
        if valid is not None:
            conditions.append(Inspection.is_valid == valid)
        if product_name:
            conditions.append(Inspection.product_name.ilike(f"%{product_name}%"))
        if date_from:
            conditions.append(Inspection.created_at >= date_from)
        if date_to:
            conditions.append(Inspection.created_at <= date_to)

        for cond in conditions:
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)

        sort_map = {
            "newest":          Inspection.created_at.desc(),
            "oldest":          Inspection.created_at.asc(),
            "confidence_desc": Inspection.confidence.desc(),
            "confidence_asc":  Inspection.confidence.asc(),
        }
        stmt = stmt.order_by(sort_map.get(sort, Inspection.created_at.desc()))
        stmt = stmt.limit(limit).offset(offset)

        items = list(self.db.execute(stmt).scalars().all())
        total = self.db.execute(count_stmt).scalar_one()
        return items, total

    # ── Sprint 6 — métricas individuais (mantidas para compatibilidade) ───────

    def count_total(self) -> int:
        return self.db.execute(select(func.count()).select_from(Inspection)).scalar_one()

    def count_by_validity(self, valid: bool) -> int:
        return self.db.execute(
            select(func.count())
            .select_from(Inspection)
            .where(Inspection.is_valid == valid)
        ).scalar_one()

    def last_n_hours(self, hours: int = 24) -> list[Inspection]:
        """
        Retorna inspeções das últimas N horas como objetos Python.

        AVISO (Sprint 9B.3): carrega TODOS os objetos em memória.
        A 5fps/24h = 432.000 rows ≈ 144MB RAM por chamada.
        Use hourly_breakdown_sql() para aggregações de dashboard em produção.
        Mantido para compatibilidade com testes existentes.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_naive = cutoff.replace(tzinfo=None)
        stmt = (
            select(Inspection)
            .where(Inspection.created_at >= cutoff_naive)
            .order_by(Inspection.created_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def hourly_breakdown(self, hours: int = 24) -> list[dict]:
        """
        Aggregação em Python — O(N) memória.

        AVISO (Sprint 9B.3): use hourly_breakdown_sql() em produção.
        Mantido para compatibilidade com testes existentes.
        """
        rows = self.last_n_hours(hours=hours)
        buckets: dict[str, dict] = {}
        for row in rows:
            bucket_key = row.created_at.replace(minute=0, second=0, microsecond=0)
            key = bucket_key.isoformat()
            if key not in buckets:
                buckets[key] = {"hour": key, "total": 0, "approved": 0, "rejected": 0}
            buckets[key]["total"] += 1
            if row.is_valid:
                buckets[key]["approved"] += 1
            else:
                buckets[key]["rejected"] += 1
        return [buckets[k] for k in sorted(buckets.keys())]

    # ── Sprint 9A ─────────────────────────────────────────────────────────────

    def update_decision(
        self,
        inspection_id: int,
        decision: str,
        decision_reason: str | None = None,
    ) -> Inspection | None:
        inspection = self.get_by_id(inspection_id)
        if inspection is None:
            return None
        inspection.decision = decision
        inspection.decision_reason = decision_reason
        inspection.reviewed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(inspection)
        return inspection

    def count_by_decision(self, decision: str) -> int:
        return self.db.execute(
            select(func.count())
            .select_from(Inspection)
            .where(Inspection.decision == decision)
        ).scalar_one()

    # ── Sprint 9B.3 — Queries consolidadas (P0) ──────────────────────────────

    def get_aggregate_stats(self, line_id: int | None = None) -> dict:
        """
        Retorna todas as métricas de contagem em UMA única query SQL.

        Sprint 9B.3 — substitui 6 COUNT() separados por 1 SELECT com CASE/WHEN.
        Sprint 10C.2 — parâmetro opcional `line_id` filtra por linha de
        produção; None (default) mantém o comportamento agregado original
        — nenhum caller existente precisa ser modificado.

        Antes: 6 round-trips ao banco por request de métricas.
        Depois: 1 round-trip — 83% menos latência de banco em get_metrics().

        Compatível com PostgreSQL (produção) e SQLite (testes).
        """
        stmt = select(
            func.count().label("total"),
            func.sum(
                case((Inspection.is_valid == True, 1), else_=0)  # noqa: E712
            ).label("valid_count"),
            func.sum(
                case((Inspection.is_valid == False, 1), else_=0)  # noqa: E712
            ).label("invalid_count"),
            func.sum(
                case((Inspection.decision == "APPROVED", 1), else_=0)
            ).label("dec_approved"),
            func.sum(
                case((Inspection.decision == "REJECTED", 1), else_=0)
            ).label("dec_rejected"),
            func.sum(
                case((Inspection.decision == "PENDING", 1), else_=0)
            ).label("dec_pending"),
        ).select_from(Inspection)

        if line_id is not None:
            stmt = stmt.where(Inspection.line_id == line_id)

        row = self.db.execute(stmt).one()

        # SUM retorna NULL quando a tabela está vazia — normaliza para 0
        return {
            "total":         int(row.total or 0),
            "valid_count":   int(row.valid_count or 0),
            "invalid_count": int(row.invalid_count or 0),
            "dec_approved":  int(row.dec_approved or 0),
            "dec_rejected":  int(row.dec_rejected or 0),
            "dec_pending":   int(row.dec_pending or 0),
        }

    def hourly_breakdown_sql(self, hours: int = 24, line_id: int | None = None) -> list[dict]:
        """
        Agrega inspeções por hora usando GROUP BY no banco de dados.

        Sprint 9B.3 — substitui last_n_hours() + Python aggregation.
        Sprint 10C.2 — parâmetro opcional `line_id` filtra por linha;
        None (default) mantém o comportamento agregado original.

        Antes: carrega todos os objetos em RAM, agrega em Python.
          A 5fps/24h: 432.000 rows ≈ 144MB RAM por chamada — O(N) memória.

        Depois: SQL GROUP BY — retorna apenas 24 buckets independente do volume.
          O(1) memória. Usa index ix_inspections_is_valid_created_at (Sprint 9B.1).

        Compatibilidade PostgreSQL/SQLite:
          - PostgreSQL: DATE_TRUNC('hour', created_at)
          - SQLite:     strftime('%Y-%m-%dT%H:00:00', created_at)
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_naive = cutoff.replace(tzinfo=None)

        # Detecta dialeto via bind do session
        try:
            dialect = self.db.bind.dialect.name  # type: ignore[union-attr]
        except Exception:
            dialect = "sqlite"

        if dialect == "postgresql":
            hour_expr = func.date_trunc("hour", Inspection.created_at)
        else:
            hour_expr = func.strftime("%Y-%m-%dT%H:00:00", Inspection.created_at)

        stmt = (
            select(
                hour_expr.label("hour"),
                func.count().label("total"),
                func.sum(
                    case((Inspection.is_valid == True, 1), else_=0)  # noqa: E712
                ).label("approved"),
                func.sum(
                    case((Inspection.is_valid == False, 1), else_=0)  # noqa: E712
                ).label("rejected"),
            )
            .where(Inspection.created_at >= cutoff_naive)
        )
        if line_id is not None:
            stmt = stmt.where(Inspection.line_id == line_id)
        stmt = stmt.group_by(hour_expr).order_by(hour_expr)

        rows = self.db.execute(stmt).all()

        return [
            {
                "hour":     str(row.hour) if row.hour else "",
                "total":    int(row.total or 0),
                "approved": int(row.approved or 0),
                "rejected": int(row.rejected or 0),
            }
            for row in rows
        ]
