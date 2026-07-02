import logging
from typing import Any

from src.config import personal, settings
from src.db.connection import get_session
from src.db.models import Instrument
from src.db.models import Portfolio as PortModel
from src.scheduler.collectors import fetch_price_history_for_instrument
from src.trading.brokers.tbank import TBankClient

logger = logging.getLogger(__name__)


async def sync_portfolio_from_broker(account_id: str = "", user_id: int = 0) -> dict[str, Any]:
    if not settings.tinkoff_token:
        return {"status": "no_token", "positions_synced": 0}

    use_sandbox = settings.tinkoff_sandbox
    stats: dict[str, Any] = {"status": "ok", "positions_synced": 0, "errors": []}

    async with TBankClient(use_sandbox=use_sandbox) as client:
        accounts = await client.get_accounts()
        if not accounts:
            return {"status": "no_accounts", **stats}

        targets: list[str] = [account_id] if account_id else [str(a["id"]) for a in accounts]
        all_positions: list[dict[str, Any]] = []
        for target in targets:
            try:
                all_positions.extend(await client.get_portfolio(target))
            except Exception as e:
                stats["errors"].append(f"Account {target}: {e}")
                logger.warning("Sync failed for account %s: %s", target, e)

    db = get_session()
    synced_instrument_ids: set[int] = set()
    try:
        for pos in all_positions:
            try:
                figi = pos["figi"]
                inst = db.query(Instrument).filter_by(figi=figi).first()
                if not inst:
                    ticker = pos.get("ticker", figi)
                    # fallback — ищем по тикеру (мог быть создан с другим FIGI от MOEX)
                    inst = db.query(Instrument).filter_by(ticker=ticker).first()
                    if inst:
                        # обновляем FIGI на T-Bank (он точнее)
                        inst.figi = figi
                        db.flush()
                    else:
                        inst_type = pos.get("instrument_type", "stock")
                        logger.info("Auto-creating instrument %s (figi=%s) from broker portfolio", ticker, figi)
                        inst = Instrument(
                            ticker=ticker,
                            full_name=ticker,
                            figi=figi,
                            instrument_type=inst_type,
                        )
                        db.add(inst)
                        db.flush()
                        try:
                            await fetch_price_history_for_instrument(ticker, inst_type)
                        except Exception as p_e:
                            logger.warning("Failed to fetch price history for new %s: %s", ticker, p_e)

                qty = pos["quantity"]
                avg_price = pos["average_price"]

                existing = db.query(PortModel).filter_by(user_id=user_id, instrument_id=inst.id).first()
                if existing:
                    existing.quantity = qty
                    existing.avg_price = avg_price
                else:
                    db.add(PortModel(user_id=user_id, instrument_id=inst.id, quantity=qty, avg_price=avg_price))
                synced_instrument_ids.add(int(inst.id))
                stats["positions_synced"] += 1
                db.commit()
            except Exception as e:
                db.rollback()
                stats["errors"].append(str(e))
                logger.warning("Sync error for position: %s", e)

        # Орфанные позиции — больше не в портфеле брокера
        orphaned = (
            db.query(PortModel)
            .filter(
                PortModel.user_id == user_id,
                PortModel.instrument_id.notin_(synced_instrument_ids),
            )
            .all()
        )
        sync_cfg = personal.get("sync", {})
        auto_remove = bool(sync_cfg.get("auto_remove_orphans", False)) if isinstance(sync_cfg, dict) else False

        for orphan in orphaned:
            ticker = orphan.instrument.ticker if orphan.instrument else "?"
            qty = orphan.quantity or 0
            price = orphan.avg_price or 0
            value = qty * price

            if auto_remove:
                logger.warning(
                    "Removing orphaned position %s (%d shares, ~%.0f RUB) — auto_remove_orphans=true",
                    ticker, qty, value,
                )
                db.delete(orphan)
                stats.setdefault("removed", 0)
                stats["removed"] += 1
            else:
                logger.warning(
                    "Orphaned position detected: %s (%d shares, ~%.0f RUB) — NOT removed. "
                    "Set sync.auto_remove_orphans=true in personal_settings.yaml to auto-remove.",
                    ticker, qty, value,
                )
                stats.setdefault("orphans_skipped", 0)
                stats["orphans_skipped"] += 1

        db.commit()
    finally:
        db.close()

    logger.info("Synced %d positions from broker", stats["positions_synced"])
    return stats
