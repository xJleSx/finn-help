import logging
from datetime import date as date_type
from typing import Any

from sqlalchemy import select

from src.config import personal, settings
from src.db.connection import get_async_session
from src.db.models import Instrument
from src.db.models import Portfolio as PortModel
from src.db.models import Price as PriceModel
from src.scheduler.collectors import fetch_price_history_for_instrument
from src.trading.brokers.tbank import TBankClient

logger = logging.getLogger(__name__)


async def sync_portfolio_from_broker(account_id: str = "", user_id: int = 0) -> dict[str, Any]:
    if not settings.tinkoff_token:
        return {"status": "no_token", "positions_synced": 0}

    use_sandbox = settings.tinkoff_sandbox
    stats: dict[str, Any] = {"status": "ok", "positions_synced": 0, "errors": []}

    try:
        client = TBankClient(use_sandbox=use_sandbox)
    except RuntimeError as e:
        logger.warning("TBank init failed: %s", e)
        return {"status": "sdk_missing", "positions_synced": 0}

    async with client:
        accounts = await client.get_accounts()
        if not accounts:
            return {"status": "no_accounts", **stats}

        targets: list[str] = [account_id] if account_id else [str(a.get("id", "")) for a in accounts]
        all_positions: list[dict[str, Any]] = []
        for target in targets:
            try:
                all_positions.extend(await client.get_portfolio(target))
            except Exception as e:
                stats["errors"].append(f"Account {target}: {e}")
                logger.warning("Sync failed for account %s: %s", target, e)

    async with get_async_session() as db:
        synced_instrument_ids: set[int] = set()
        for pos in all_positions:
            try:
                figi = pos.get("figi") or ""
                result = await db.execute(select(Instrument).where(Instrument.figi == figi))
                inst = result.scalars().first()
                if not inst:
                    ticker = pos.get("ticker", figi)
                    result = await db.execute(select(Instrument).where(Instrument.ticker == ticker))
                    inst = result.scalars().first()
                    if inst:
                        inst.figi = figi
                        await db.flush()
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
                        await db.flush()
                        try:
                            await fetch_price_history_for_instrument(ticker, inst_type)
                        except Exception as p_e:
                            logger.warning("Failed to fetch price history for new %s: %s", ticker, p_e)

                qty = pos.get("quantity", 0)
                avg_price = pos.get("average_price", 0.0)
                clean_price = pos.get("current_price", 0.0)
                is_bond = pos.get("instrument_type", "") == "bond"
                dirty_price = pos.get("dirty_price", clean_price) if is_bond else clean_price

                # Save price from broker to Price table for fresh portfolio display
                # For bonds: open=clean_price (P&L), close=dirty_price (current value incl NKD)
                if clean_price > 0:
                    existing_price = await db.execute(
                        select(PriceModel).where(
                            PriceModel.instrument_id == inst.id,
                            PriceModel.date == date_type.today(),
                        )
                    )
                    price_row = existing_price.scalar_one_or_none()
                    if price_row:
                        price_row.open = clean_price
                        price_row.close = dirty_price
                    else:
                        db.add(PriceModel(
                            instrument_id=inst.id,
                            date=date_type.today(),
                            open=clean_price,
                            high=max(clean_price, dirty_price),
                            low=min(clean_price, dirty_price),
                            close=dirty_price,
                            volume=0,
                        ))

                result = await db.execute(select(PortModel).where(PortModel.user_id == user_id, PortModel.instrument_id == inst.id))
                existing = result.scalars().first()
                if existing:
                    existing.quantity = qty
                    existing.avg_price = avg_price
                else:
                    db.add(PortModel(user_id=user_id, instrument_id=inst.id, quantity=qty, avg_price=avg_price))
                synced_instrument_ids.add(int(inst.id))
                stats["positions_synced"] += 1
                await db.commit()
            except Exception as e:
                await db.rollback()
                stats["errors"].append(str(e))
                logger.warning("Sync error for position: %s", e)

        result = await db.execute(
            select(PortModel).where(
                PortModel.user_id == user_id,
                PortModel.instrument_id.notin_(synced_instrument_ids),
            )
        )
        orphaned = result.scalars().all()
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
                    ticker,
                    qty,
                    value,
                )
                await db.delete(orphan)
                stats.setdefault("removed", 0)
                stats["removed"] += 1
            else:
                logger.warning(
                    "Orphaned position detected: %s (%d shares, ~%.0f RUB) — NOT removed. "
                    "Set sync.auto_remove_orphans=true in personal_settings.yaml to auto-remove.",
                    ticker,
                    qty,
                    value,
                )
                stats.setdefault("orphans_skipped", 0)
                stats["orphans_skipped"] += 1

        await db.commit()

    logger.info("Synced %d positions from broker", stats["positions_synced"])
    return stats
