from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func as sqlfunc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from src.core.health import health_registry
from src.db.models import AltDataPoint, BondOffering, CompanyProfile, CorporateEvent, FinancialReport, Instrument, Price, Signal
from src.interfaces.api.auth import get_db
from src.interfaces.api.schemas import HealthResponse

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/health", response_model=HealthResponse)
async def health(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    healthy = True
    checks: dict[str, str] = {}
    components: dict[str, Any] = {}

    try:
        from src.core.resilience import get_all_circuit_states

        cb_states = get_all_circuit_states()
        if cb_states:
            components["circuit_breakers"] = cb_states
        for name, snap in cb_states.items():
            if snap.get("state") == "open":
                checks[f"circuit_breaker_{name}"] = f"OPEN ({snap.get('failure_count', 0)} failures)"
    except Exception:
        logger.exception("Unhandled exception")
        components["circuit_breakers"] = None

    try:
        result = await db.execute(select(sqlfunc.count(Instrument.id)))
        val = result.scalar()
        components["instruments"] = int(val) if val is not None else 0
    except Exception:
        logger.exception("Unhandled exception")
        components["instruments"] = None

    try:
        from src.scheduler.service import _running

        components["scheduler_running"] = _running
    except Exception:
        logger.exception("Unhandled exception")
        components["scheduler_running"] = None

    try:
        last_signal = await db.execute(select(Signal.date).order_by(Signal.date.desc()).limit(1))
        row: Any = last_signal.scalar_one_or_none()
        if row is not None:
            components["last_signal_at"] = row.isoformat() if hasattr(row, "isoformat") else str(row)
        else:
            components["last_signal_at"] = None
    except Exception:
        logger.exception("Unhandled exception")
        components["last_signal_at"] = None

    try:
        last_price = await db.execute(select(Price.date).order_by(Price.date.desc()).limit(1))
        price_row: Any = last_price.scalar_one_or_none()
        if price_row is not None:
            dt_str = price_row.isoformat() if hasattr(price_row, "isoformat") else str(price_row)
            components["last_price_date"] = dt_str
            try:
                days: int = (date.today() - price_row).days
                components["price_staleness_days"] = days
                if days > 2:
                    checks["staleness"] = f"Последняя цена от {dt_str}, {days}д назад"
            except TypeError:
                pass
    except Exception:
        logger.exception("Unhandled exception")
        components["last_price_date"] = None

    try:
        from src.model_registry import _load_registry

        registry = _load_registry()
        if registry:
            models_summary = {}
            for name, entry in registry.items():
                latest = entry.get("latest")
                if latest:
                    models_summary[name] = str(latest)
            components["models"] = models_summary
    except Exception:
        logger.exception("Unhandled exception")
        components["models"] = None

    try:
        total_inst = components.get("instruments") or 1

        for table, label, model in [
            (CompanyProfile, "profile_coverage", CompanyProfile),
            (FinancialReport, "report_coverage", FinancialReport),
            (BondOffering, "bond_coverage", BondOffering),
            (CorporateEvent, "event_coverage", CorporateEvent),
            (AltDataPoint, "alt_data_count", AltDataPoint),
        ]:
            cnt = await db.execute(select(sqlfunc.count(model.id)))
            cval: Any = cnt.scalar()
            if label.endswith("_coverage") and cval is not None:
                pct = round(cval / total_inst * 100, 1) if total_inst > 0 else 0
                components[label] = f"{cval}/{total_inst} ({pct}%)"
            else:
                components[label] = int(cval) if cval is not None else 0
    except Exception as e:
        logger.warning("Health check component failed: %s", e)

    try:
        from src.db.models import AlertLog

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        alert_cnt = await db.execute(select(sqlfunc.count(AlertLog.id)).where(AlertLog.created_at >= cutoff))
        components["alerts_7d"] = int(alert_cnt.scalar() or 0)
    except Exception:
        logger.exception("Unhandled exception")
        components["alerts_7d"] = None

    for name, check_fn in health_registry.items():
        if name not in components:
            try:
                components[name] = await check_fn()
            except Exception:
                logger.exception("Unhandled exception")
                components[name] = "error"

    status = "degraded" if checks and healthy else "unhealthy" if not healthy else "ok"
    return {
        "status": status,
        "checks": checks or None,
        "components": components,
    }
