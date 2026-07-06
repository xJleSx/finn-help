from typing import Any, cast

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from src.collectors.cbr import CBRCollector
from src.config import personal
from src.db.connection import get_session
from src.db.models import News
from src.interfaces.telegram_guard import guard
from src.interfaces.telegram_helpers import (
    _chunk_text,
    html_escape,
)

logger = structlog.get_logger(__name__)


@guard(with_cooldown=True)
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        db = get_session()
        try:
            rows = db.query(News).order_by(News.published_at.desc().nullslast()).limit(50).all()
            if not rows:
                await update.effective_message.reply_text("Нет новостей.")
                return
            text = "📰 <b>Последние 50 новостей:</b>\n\n"
            for i, n in enumerate(rows, 1):
                title = html_escape((n.title or "")[:120])
                pub = n.published_at.strftime("%d.%m.%Y") if n.published_at else "?"
                src = html_escape(n.source_name or n.source_type or "?")
                sent = f" ({n.sentiment_score:+.2f})" if n.sentiment_score is not None else ""
                text += f"{i}. [{pub}] {title}{sent}\n"
                if n.source_name:
                    text += f"   — {src}\n"
                text += "\n"
            for chunk in _chunk_text(text, 4096):
                await update.effective_message.reply_text(chunk, parse_mode="HTML")
        finally:
            db.close()
    except Exception:
        logger.warning("News command error", exc_info=True)
        await update.effective_message.reply_text("❌ Не удалось загрузить новости.")


@guard()
async def pulse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    author = args[0] if args else None
    if not author:
        from src.config import personal as _personal

        social_sources: dict[str, Any] = cast(dict[str, Any], _personal.get("social_sources", {}))
        pulse_config: dict[str, Any] = cast(dict[str, Any], social_sources.get("pulse", {}))
        authors: list[Any] = cast(list[Any], pulse_config.get("authors", []))
        await update.effective_message.reply_text("Отслеживаемые авторы Пульса:\n" + "\n".join(f"  @{a}" for a in authors))
        return

    from src.social.registry import registry

    registry.build_from_config()
    src = registry.get("pulse")
    if not src:
        await update.effective_message.reply_text("Пульс не настроен")
        return

    stats = await src.fetch_author_stats(author)
    if stats:
        await update.effective_message.reply_text(
            f"📊 @{author}\n  Подписчиков: {stats.get('followers', '?')}\n  Доходность: {stats.get('yield', '?')}%"
        )
    else:
        await update.effective_message.reply_text(f"Не удалось получить данные @{author}")


@guard(with_cooldown=True)
async def rates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cbr = CBRCollector()
    try:
        rates = await cbr.get_rates()
        majors = ["USD", "EUR", "CNY", "GBP", "KZT", "TRY"]
        lines = ["\U0001f3e6 Курсы ЦБ РФ:\n"]
        for r in rates:
            if r["code"] in majors:
                lines.append(f"  {r['code']}: {r['value']:.2f} \u20bd")
        await update.effective_message.reply_text("\n".join(lines))
    except Exception:
        logger.warning("Rates error", exc_info=True)
        await update.effective_message.reply_text("\u274c Не удалось получить курсы. Попробуйте позже.")


@guard()
async def social_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    ticker = args[0].upper() if args else None
    if not ticker:
        await update.effective_message.reply_text("Использование: /social TICKER\nПример: /social SBER")
        return

    from src.social.sentiment.aggregator import aggregator

    result = aggregator.get_ticker_sentiment(ticker)
    if result["count"] == 0:
        await update.effective_message.reply_text(f"\U0001f50e Нет social-данных для {ticker}")
        return

    emoji = "\U0001f7e2" if result["score"] > 0.1 else "\U0001f534" if result["score"] < -0.1 else "\U0001f7e1"
    await update.effective_message.reply_text(
        f"{emoji} Social Sentiment — {ticker}\n"
        f"  Score: {result['score']:.3f}\n"
        f"  Расхождение: {result['divergence']:.3f}\n"
        f"  Постов проанализировано: {result['count']}\n"
        f"  Средняя уверенность: {result.get('avg_confidence', 0):.3f}"
    )


@guard(with_cooldown=True)
async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    uid = update.effective_user.id
    args = context.args or []
    db = get_session()
    try:
        from src.db.models import SmartAlertRule

        if not args or args[0] == "list":
            rules = (
                db.query(SmartAlertRule)
                .filter(
                    SmartAlertRule.user_id == uid,
                    SmartAlertRule.rule_type == "price",
                )
                .all()
            )
            if rules:
                lines = ["<b>💰 Price alerts</b>"]
                for r in rules:
                    direction = ">" if r.condition == "gt" else "<" if r.condition == "lt" else r.condition
                    status = "✅" if r.enabled else "❌"
                    name = f" ({html_escape(r.name)})" if r.name else ""
                    lines.append(f"{status} <b>{html_escape(r.ticker)}</b> {direction} {r.threshold}{name}")
                await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
            else:
                await update.effective_message.reply_text("Нет price-алертов. Создайте: /price add TICKER > 250")
            return

        if args[0] == "add":
            if len(args) < 4:
                await update.effective_message.reply_text("Использование: /price add TICKER > 250 [название]\nНапример: /price add SBER > 300")
                return
            ticker = args[1].upper()
            condition = "gt" if args[2] == ">" else "lt" if args[2] == "<" else "gte" if args[2] == ">=" else "lte" if args[2] == "<=" else "eq"
            try:
                threshold = float(args[3])
            except ValueError:
                await update.effective_message.reply_text("Порог должен быть числом")
                return
            name = " ".join(args[4:]) if len(args) > 4 else None
            existing = (
                db.query(SmartAlertRule)
                .filter(
                    SmartAlertRule.user_id == uid,
                    SmartAlertRule.ticker == ticker,
                    SmartAlertRule.rule_type == "price",
                    SmartAlertRule.condition == condition,
                    SmartAlertRule.threshold == threshold,
                )
                .first()
            )
            if existing:
                await update.effective_message.reply_text(f"ℹ️ Такой price-алерт уже существует (id={existing.id})")
                return
            rule = SmartAlertRule(
                user_id=uid,
                name=name,
                rule_type="price",
                ticker=ticker,
                condition=condition,
                threshold=threshold,
                enabled=True,
            )
            db.add(rule)
            db.commit()
            direction = ">" if condition == "gt" else "<" if condition == "lt" else condition
            await update.effective_message.reply_text(
                f"✅ Price-алерт: <b>{html_escape(ticker)}</b> {direction} {threshold}",
                parse_mode="HTML",
            )
            return

        if args[0] == "remove":
            if len(args) < 2:
                await update.effective_message.reply_text("Использование: /price remove <id>")
                return
            try:
                rule_id = int(args[1])
            except ValueError:
                await update.effective_message.reply_text("ID должен быть числом")
                return
            rule = (
                db.query(SmartAlertRule)
                .filter(
                    SmartAlertRule.id == rule_id,
                    SmartAlertRule.user_id == uid,
                    SmartAlertRule.rule_type == "price",
                )
                .first()
            )
            if not rule:
                await update.effective_message.reply_text("Price-алерт не найден")
                return
            db.delete(rule)
            db.commit()
            await update.effective_message.reply_text(f"✅ Price-алерт #{rule_id} удалён")
            return

        if args[0] == "toggle":
            if len(args) < 2:
                await update.effective_message.reply_text("Использование: /price toggle <id>")
                return
            try:
                rule_id = int(args[1])
            except ValueError:
                await update.effective_message.reply_text("ID должен быть числом")
                return
            rule = (
                db.query(SmartAlertRule)
                .filter(
                    SmartAlertRule.id == rule_id,
                    SmartAlertRule.user_id == uid,
                    SmartAlertRule.rule_type == "price",
                )
                .first()
            )
            if not rule:
                await update.effective_message.reply_text("Price-алерт не найден")
                return
            rule.enabled = not rule.enabled
            db.commit()
            status = "включён" if rule.enabled else "отключён"
            await update.effective_message.reply_text(f"✅ Price-алерт #{rule_id} {status}")
            return

        await update.effective_message.reply_text(
            "Команды:\n"
            "/price list — список price-алертов\n"
            "/price add TICKER > 250 [название] — создать\n"
            "/price remove <id> — удалить\n"
            "/price toggle <id> — вкл/выкл"
        )
    except Exception:
        logger.exception("price_cmd_failed", user_id=uid)
        await update.effective_message.reply_text("❌ Ошибка. Попробуйте позже.")
    finally:
        db.close()
