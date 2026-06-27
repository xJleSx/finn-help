import logging
from datetime import date, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.db.models import Instrument, Price

logger = logging.getLogger(__name__)


class SectorAnalyzer:
    SECTOR_KEYWORDS: dict[str, list[str]] = {
        "Финансы": ["сбер", "втб", "банк", "мосбиржа", "спб биржа", "мкб", "совкомбанк", "тинькофф"],
        "Нефть": ["нефть", "газпром", "лукойл", "роснефть", "татнефть", "башнефть", "транснефть", "новатэк"],
        "Металлы": ["металл", "норникель", "северсталь", "нлмк", "ммк", "алюминий", "руп", "полюс"],
        "IT": ["яндекс", "vk", "оzon", "mail", "астра", "софт", "cian", "headhunter", "техно"],
        "Потребительский": ["магнит", "x5", "пятерочка", "фикс прайс", "черкизово", "белуга", "новабев"],
        "Телеком": ["мтс", "ростел", "мегафон", "т2", "теле2"],
        "Энергетика": ["интер рао", "юнипро", "русгидро", "энергетик", "фск"],
        "Химия": ["фосагро", "акрон", "уралкалий", "химия"],
        "Транспорт": ["аэрофлот", "ржд", "транскон", "депо"],
    }

    def sector_for(self, name: str, ticker: str) -> str:
        name_lower = (name + " " + ticker).lower()
        for sector, keywords in self.SECTOR_KEYWORDS.items():
            if any(kw in name_lower for kw in keywords):
                return sector
        return "Прочее"

    def compute_sector_performance(self, db: Session, days: int = 30) -> dict[str, float]:
        cutoff = date.today() - timedelta(days=days)
        instruments = db.query(Instrument).all()
        sector_returns: dict[str, list[float]] = {}

        for inst in instruments:
            first = (
                db.query(Price)
                .filter(Price.instrument_id == inst.id, Price.date >= cutoff)
                .order_by(Price.date)
                .first()
            )
            last = (
                db.query(Price)
                .filter(Price.instrument_id == inst.id, Price.date >= cutoff)
                .order_by(Price.date.desc())
                .first()
            )
            if not first or not last or not first.close or not last.close or first.close <= 0:
                continue
            ret = float((last.close - first.close) / first.close)
            sector = self.sector_for(str(inst.full_name or ""), str(inst.ticker))
            if sector not in sector_returns:
                sector_returns[sector] = []
            sector_returns[sector].append(ret)

        return {
            sector: round(float(np.mean(returns)), 4) for sector, returns in sector_returns.items() if len(returns) >= 2
        }

    def compute_sector_correlation(self, db: Session, days: int = 90) -> dict[str, dict[str, float]]:
        cutoff = date.today() - timedelta(days=days)
        instruments = db.query(Instrument).all()
        sector_prices: dict[str, list[float]] = {}

        for inst in instruments:
            prices = (
                db.query(Price).filter(Price.instrument_id == inst.id, Price.date >= cutoff).order_by(Price.date).all()
            )
            closes = [float(p.close) for p in prices if p.close and p.close > 0]
            if len(closes) < 20:
                continue
            sector = self.sector_for(str(inst.full_name or ""), str(inst.ticker))
            if sector not in sector_prices:
                sector_prices[sector] = closes[:]
            elif len(closes) > len(sector_prices[sector]):
                sector_prices[sector] = closes[: len(sector_prices[sector])]
            else:
                sector_prices[sector] = sector_prices[sector][: len(closes)]

        sectors = list(sector_prices.keys())
        corr: dict[str, dict[str, float]] = {}
        for i in range(len(sectors)):
            corr[sectors[i]] = {}
            for j in range(len(sectors)):
                if i == j:
                    corr[sectors[i]][sectors[j]] = 1.0
                else:
                    a = np.array(sector_prices[sectors[i]])
                    b = np.array(sector_prices[sectors[j]])
                    if len(a) >= 10 and len(b) >= 10:
                        returns_a = np.diff(a) / a[:-1]
                        returns_b = np.diff(b) / b[:-1]
                        min_len = min(len(returns_a), len(returns_b))
                        c = np.corrcoef(returns_a[:min_len], returns_b[:min_len])
                        corr[sectors[i]][sectors[j]] = round(float(c[0, 1]), 3)
                    else:
                        corr[sectors[i]][sectors[j]] = 0.0
        return corr

    def compute_sector_volatility(self, db: Session, days: int = 30) -> dict[str, float]:
        cutoff = date.today() - timedelta(days=days)
        instruments = db.query(Instrument).all()
        sector_vols: dict[str, list[float]] = {}

        for inst in instruments:
            prices = (
                db.query(Price).filter(Price.instrument_id == inst.id, Price.date >= cutoff).order_by(Price.date).all()
            )
            closes = [float(p.close) for p in prices if p.close and p.close > 0]
            if len(closes) < 10:
                continue
            returns = np.diff(closes) / closes[:-1]
            vol = float(np.std(returns) * np.sqrt(252))
            sector = self.sector_for(str(inst.full_name or ""), str(inst.ticker))
            if sector not in sector_vols:
                sector_vols[sector] = []
            sector_vols[sector].append(vol)

        return {sector: round(float(np.mean(vols)), 4) for sector, vols in sector_vols.items() if len(vols) >= 2}

    async def compute_sector_performance_async(self, db: AsyncSession, days: int = 30) -> dict[str, float]:
        cutoff = date.today() - timedelta(days=days)
        result = await db.execute(select(Instrument))
        instruments = result.scalars().all()
        sector_returns: dict[str, list[float]] = {}

        for inst in instruments:
            first_result = await db.execute(
                select(Price).where(Price.instrument_id == inst.id, Price.date >= cutoff).order_by(Price.date).limit(1)
            )
            first = first_result.scalar_one_or_none()
            last_result = await db.execute(
                select(Price)
                .where(Price.instrument_id == inst.id, Price.date >= cutoff)
                .order_by(Price.date.desc())
                .limit(1)
            )
            last = last_result.scalar_one_or_none()
            if not first or not last or not first.close or not last.close or first.close <= 0:
                continue
            ret = float((last.close - first.close) / first.close)
            sector = self.sector_for(str(inst.full_name or ""), str(inst.ticker))
            if sector not in sector_returns:
                sector_returns[sector] = []
            sector_returns[sector].append(ret)

        return {
            sector: round(float(np.mean(returns)), 4) for sector, returns in sector_returns.items() if len(returns) >= 2
        }

    async def compute_sector_correlation_async(self, db: AsyncSession, days: int = 90) -> dict[str, dict[str, float]]:
        cutoff = date.today() - timedelta(days=days)
        result = await db.execute(select(Instrument))
        instruments = result.scalars().all()
        sector_prices: dict[str, list[float]] = {}

        for inst in instruments:
            price_result = await db.execute(
                select(Price).where(Price.instrument_id == inst.id, Price.date >= cutoff).order_by(Price.date)
            )
            prices = price_result.scalars().all()
            closes = [float(p.close) for p in prices if p.close and p.close > 0]
            if len(closes) < 20:
                continue
            sector = self.sector_for(str(inst.full_name or ""), str(inst.ticker))
            if sector not in sector_prices:
                sector_prices[sector] = closes[:]
            elif len(closes) > len(sector_prices[sector]):
                sector_prices[sector] = closes[: len(sector_prices[sector])]
            else:
                sector_prices[sector] = sector_prices[sector][: len(closes)]

        sectors = list(sector_prices.keys())
        corr: dict[str, dict[str, float]] = {}
        for i in range(len(sectors)):
            corr[sectors[i]] = {}
            for j in range(len(sectors)):
                if i == j:
                    corr[sectors[i]][sectors[j]] = 1.0
                else:
                    a = np.array(sector_prices[sectors[i]])
                    b = np.array(sector_prices[sectors[j]])
                    if len(a) >= 10 and len(b) >= 10:
                        returns_a = np.diff(a) / a[:-1]
                        returns_b = np.diff(b) / b[:-1]
                        min_len = min(len(returns_a), len(returns_b))
                        c = np.corrcoef(returns_a[:min_len], returns_b[:min_len])
                        corr[sectors[i]][sectors[j]] = round(float(c[0, 1]), 3)
                    else:
                        corr[sectors[i]][sectors[j]] = 0.0
        return corr

    async def compute_sector_volatility_async(self, db: AsyncSession, days: int = 30) -> dict[str, float]:
        cutoff = date.today() - timedelta(days=days)
        result = await db.execute(select(Instrument))
        instruments = result.scalars().all()
        sector_vols: dict[str, list[float]] = {}

        for inst in instruments:
            price_result = await db.execute(
                select(Price).where(Price.instrument_id == inst.id, Price.date >= cutoff).order_by(Price.date)
            )
            prices = price_result.scalars().all()
            closes = [float(p.close) for p in prices if p.close and p.close > 0]
            if len(closes) < 10:
                continue
            returns = np.diff(closes) / closes[:-1]
            vol = float(np.std(returns) * np.sqrt(252))
            sector = self.sector_for(str(inst.full_name or ""), str(inst.ticker))
            if sector not in sector_vols:
                sector_vols[sector] = []
            sector_vols[sector].append(vol)

        return {sector: round(float(np.mean(vols)), 4) for sector, vols in sector_vols.items() if len(vols) >= 2}


sector_analyzer = SectorAnalyzer()
