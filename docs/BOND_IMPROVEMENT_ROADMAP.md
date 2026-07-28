# Bond Module Improvement Roadmap

Based on comparison between current finn-help implementation and advanced bond portfolio algorithm.

## Gap Analysis

### What finn-help already does (needs improvement)

| Capability | Current | Target |
|---|---|---|
| Credit rating analysis | Scale AAA->B-, score +/- | Split by investment grade / speculative, account for portfolio size |
| YTM/spread | Spread to key rate and OFZ | Add rate cycle context (cutting -> long OFZ, hiking -> short/floater) |
| Duration | >7 years = risk | Rate-cycle-aware: cutting = bonus for long, hiking = bonus for short |
| Put option | +0.05 to score | Treat as insurance against rate hikes, affects whole strategy |
| New issues | Sort by rating -> YTM | Add portfolio context (ladder, diversification) |
| Coupon type | Float = good for rising rates | Float = bad in cutting cycle, good in hiking |
| Macro context | Generic thresholds (key_rate, CPI, OFZ, Brent, M2) | Add rate cycle direction detection, adjust bond strategy |

### What is MISSING

1. **Portfolio-level analysis** — each bond analyzed in isolation, no portfolio context (weight, correlation with other positions, default effect on portfolio)

2. **Default Impact Analysis** — no calculation of "if this bond defaults, how much must the rest earn to recover"

3. **Rate Cycle Strategy** — no logic for "cutting -> long OFZ, hiking -> floaters/short bonds"

4. **Ladder Generator** — no maturity ladder recommendation

5. **Rating-based position sizing** — no rule "rating < investment grade -> max 5-10% of portfolio"

6. **ETF/liquidity buffer role** — TMON/LQDT have no defined role; algorithm treats them as liquidity buffer

7. **Capital preservation priority** — no explicit principle "for portfolio < 50K RUB -> 73%+ in gov/quasi-gov"

### What model ADMITTED as gaps (v2 improvements)

8. **НКД и налоги не учтены** — YTM считалась без вычета НКД при покупке и налога 13% на купон. Реальная доходность на 2-3% ниже.

9. **Ликвидность без метрик** — «РЖД ликвидна» качественно, без цифр (объём торгов, спред, глубина стакана).

10. **Put-опцион качественно** — нет формулы оценки стоимости страховки от роста ставок.

11. **Формула Келли не использована** — вес спекулятивной позиции (5-10%) выбран эвристически, не по формуле.

12. **Сценарий B не смоделирован** — нет плана на случай, если ставка ЦБ не снижается.

13. **Триггеры ребалансировки** — нет автоматических правил когда пересматривать портфель.

14. **Рейтинги без источника** — нет данных об агентстве (АКРА/Эксперт РА/НКР), дате и шкале рейтинга.

15. **Инфляция не вычитается** — реальная доходность = YTM_netto − комиссия − спред − инфляция, последнего шага нет.

### What model CORRECTED — v3 (точные цифры взамен эвристик)

16. **p (вероятность погашения) для BBB+** — модель брала 96%, реальные данные АКРА: 90-93% (7-10% дефолт/год в 2025-2026). Источник: raexpert.ru, acra-ratings.ru.

17. **Recovery rate** — модель брала 40%, данные ВШЭ (59 дефолтов): средний 48.8%, с госучастием 66.7%, без госучастия 35-45%. Recovery = f(сектор, рейтинг, госучастие, тип дефолта, цикл).

18. **Комиссии брокеров** — модель брала 0.05% для Т-Банка. Реальность: Т-Банк 0.025%, БКС 0.01-0.03% + 299₽/мес, Финам 0%/0.05%, MOEX сбор ~0.01%. Нужен BROKER_CONFIG.

19. **Налог ЛДВ** — модель упомянула неточно. LDV (ст.219.1 НК) работает и на брокерском, и на ИИС-3, освобождает прирост капитала, НО не освобождает купонный доход (13% всегда). YTM_after_tax = (Coupon×0.87 + CapGain×1.0) / AvgInv.

20. **Сценариев макро** — модель моделировала 2 (A, B). Реально нужно 5: A (мягкая посадка), B (ставка не падает), C (кризис/рецессия), D (санкции/структурный сдвиг), E (волна дефолтов).

21. **Метрики ликвидности** — конкретные endpoint'ы MOEX ISS: orderbook.json (BID/ASK/DEPTH), marketdata (VALTODAY/NUMTRADES), candles (для Amihud). Board: TQOB/TQCB. 15 мин задержка.

22. **Прогноз инфляции** — нет открытого API. Источники: cbr.ru/hd_base/infl/ (факт, HTML/CSV), cbr.ru/dkp/ (ДКП PDF ежеквартально), economy.gov.ru. Рекомендация: хранить прогноз vs факт в БД.

23. **Валютная переоценка** — не учтена. Формула: RealReturn = (1+YTM) × (1+ΔFX) − 1. Актуальна если появятся замещающие облигации.

### What model CONFIRMED (v4 — вторая модель, техническая валидация)

24. **Newton-Raphson достаточен** для YTM, но нужен Brent как fallback. Гибридный подход: NR → если не сошёлся за N итераций → Brent.

25. **ΔP ≈ −D×Δr — корректно** для малых Δr (<50-100 б.п.). При больших движениях обязательна выпуклость: ΔP/P ≈ −D_mod×Δr + 0.5×C×(Δr)².

26. **Put valuation**: Option = P_putable − P_straight. Для точной оценки нужны стохастические модели (Hull-White), но для retail достаточно линейной аппроксимации.

27. **Амортизация**: нет упрощённого расчёта дюрации. Только полный график всех денежных потоков (каждый купон + каждое частичное погашение + финальное).

28. **НКД**: dirty price = clean price + AI — именно грязная цена должна быть оттоком в YTM.

29. **VALUE пороги ликвидности**: <500K низкая, 20-50M средняя, >100M высокая (вместо эвристик первой модели).

30. **Сценарий C (21%→8% за 6 мес)**: крайне маловероятен для РФ, только для стресс-тестов. Исторических прецедентов нет.

31. **Индикаторы разворота цикла**: базовая инфляция, инфляционные ожидания, риторика ЦБ (пресс-релизы), короткий конец ОФЗ, RUONIA, ставки денежного рынка, курс рубля.

32. **Recovery 2025-2026**: 30-40% для необеспеченных (первая модель: 35-45%, вторая уточняет вниз из-за ухудшения макро).

---



## Improvement Modules

### 1. DefaultRiskImpactAnalyzer

**File:** `src/analysis/bonds/default_risk_analyzer.py` (NEW)

Calculates for each position:
- `loss_if_default = position_value`
- `required_return = loss_if_default / portfolio_value` (how much rest must earn)
- `months_to_recover = required_return / (portfolio_avg_ytm / 12)`
- If `loss_if_default > 0.10 * portfolio_value` AND rating < BBB -> SELL signal

**Input:** Current portfolio positions with prices, ratings, quantities
**Output:** Per-position risk metrics + aggregate portfolio default risk

---

### 2. RateCycleAwareStrategy

**File:** `src/analysis/bonds/rate_cycle.py` (NEW)
**Modify:** `src/analysis/signals/bond_signals.py`

Detects rate cycle phase from key rate history + additional indicators:
- `cutting`: key rate decreased in last 3-6 months
- `hiking`: key rate increased in last 3-6 months
- `stable`: no clear trend

**Additional leading indicators (вторая модель):**
- Базовая инфляция (core CPI) — устойчивое снижение → сигнал к развороту
- Инфляционные ожидания населения и бизнеса (cbr.ru опросы)
- Риторика ЦБ в пресс-релизах и Докладах о ДКП (LLM sentiment)
- Короткий конец кривой ОФЗ (1-2 года) — предсказывает решения ЦБ
- RUONIA и ставки денежного рынка — опережающий индикатор
- Курс рубля и динамика импортных цен

**Composite detection:**
```python
def detect_cycle(key_rate_history, core_cpi, ruonia, short_ofz_yields, cbr_rhetoric_sentiment):
    # Если 2+ индикатора указывают на смену — переключаемся
```

**Logic:**
- cutting: long bonds (+bonus), floaters (-penalty), fixed coupon (+bonus)
- hiking: short bonds (+bonus), floaters (+bonus), long bonds (-penalty)
- stable: neutral, current logic applies

**Bond signal modification:**
Current: `duration > 7 -> score -= 0.15, risk += 0.2`
Should become: `duration > 7 AND rate_cycle == 'hiking' -> risk`; `duration > 5 AND rate_cycle == 'cutting' -> bonus`

Current: `float -> score += 0.1, "protection against rate hikes"`
Should become: `float -> score += 0.1 if hiking, score -= 0.1 if cutting`

---

### 3. BondPortfolioOptimizer

**File:** `src/analysis/bonds/bond_portfolio_optimizer.py` (NEW)
**API:** Add endpoint `/api/portfolio/bonds/optimize`

Portfolio-level analysis engine:
- Weighted average credit rating
- Concentration by issuer/sector/rating
- Default scenario simulation
- Maturity ladder visualization
- Rating distribution

**Output per portfolio:**
```
{
  "sellRecommendations": [...],
  "buyRecommendations": [...],
  "holdRecommendations": [...],
  "portfolioHealth": {
    "weightedRating": "AA-",
    "effectiveDuration": 4.2,
    "govQuasiGovPct": 65.0,
    "speculativePct": 7.5,
    "ladderGaps": ["2027", "2030"],
    "defaultScenarioLossPct": 3.2,
    "monthsToRecoverFromDefault": 2.5
  }
}
```

**Decision rules:**
- Rating < BBB AND position > 10% of portfolio -> SELL
- Rating = AAA AND YTM > 14% AND portfolio has < 50% gov -> BUY
- Speculative positions total > 10% of portfolio -> reduce
- Gov/quasi-gov < 50% of portfolio for capital < 50K RUB -> increase
- Maturity gap > 2 years in ladder -> suggest new bond for that slot

---

### 4. BondLadderGenerator

**File:** `src/analysis/bonds/bond_ladder_generator.py` (NEW)

Analyzes current maturity dates and recommends:
- Missing maturity slots in 1-3-5-7-10 year range
- Reinvestment suggestions for maturing bonds (like Selectel maturing in 2 weeks)
- Expected cash flow from maturities per year

**Output:**
```
{
  "currentLadder": {
    "2026": {"bonds": ["Селектел"], "totalValue": 2000},
    "2028": {"bonds": ["Cloud.ru"], "totalValue": 1000},
    "2029": {"bonds": ["ПР-Лизинг"], "totalValue": 1000},
    ...
  },
  "reinvestmentSuggestions": [...],
  "gaps": ["2027", "2030"]
}
```

---

### 5. Enhanced bond signals (bond_signals.py modifications)

**File:** `src/analysis/signals/bond_signals.py` (MODIFY)

Add parameters:
- `rate_cycle`: "cutting" | "hiking" | "stable"
- `portfolio_context`: dict with current position info

Modify scoring:
- YTM evaluation: add rate cycle context
- Duration: penalize/bonus based on rate cycle
- Coupon type: floaters good in hiking, bad in cutting
- Offer/put: value depends on rate cycle (put = insurance in cutting cycle)

Add default risk assessment:
- If bond_offering + portfolio_context available: calculate default impact
- If impact > threshold AND rating < BBB: override action to SELL

---

### 6. Portfolio-level bond risk profile constants

**File:** `src/constants.py` (MODIFY)

Add:
```python
BOND_PORTFOLIO_RULES = {
    "max_speculative_pct": 0.10,
    "min_gov_quasi_pct": 0.50,
    "default_recovery_months_limit": 6,
    "max_single_issuer_pct": 0.25,
    "small_portfolio_threshold": 50000,
    "small_portfolio_min_gov_pct": 0.70,
}

BOND_RATING_CATEGORIES = {
    "investment_grade": ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"],
    "speculative": ["BB+", "BB", "BB-", "B+", "B", "B-"],
    "default_risk": ["CCC+", "CCC", "CCC-", "CC", "C", "D"],
}
```

---

### 7. Extended portfolio bonds API

**File:** `src/interfaces/api/routes/portfolio_bonds.py` (MODIFY)

Add fields to `/api/portfolio/bonds` response:
- `defaultImpact` per position: loss amount, portfolio %, months to recover
- `ladder`: maturity ladder visualization
- `rateCycle`: current phase + duration recommendation
- `ratingDistribution`: { "AAA": 30%, "AA": 25%, ... }
- `healthScore`: 0-100 portfolio health metric
- `warnings`: ["11% in АЛИУМ with BB rating - high default risk"]

---

### 8. Enhanced bond analysis API

**File:** `src/interfaces/api/routes/bonds.py` (MODIFY)

Enhance `/api/instruments/{ticker}/analysis`:
- Add `portfolioContext` section: how this bond fits into typical portfolio
- Add `defaultImpact` section
- Add `rateCycleAdvice`: current rate cycle phase and bond suitability
- Improve AI analysis with rate cycle context

---

### 9. AfterTaxYieldCalculator

**File:** `src/analysis/bonds/after_tax_yield.py` (NEW)

Calculates real bond yield accounting for:
- **НКД (accrued interest)**: при покупке цена = чистая цена + НКД, реальная инвестиция выше номинала
- **Налог 13%** на купонный доход (НДФЛ для резидентов РФ)
- **Комиссия брокера** (0.05% за сделку, вход+выход)
- **Спред bid-ask** (ОФЗ ~0.3%, корп ~1.0%)
- **Инфляция** (прогноз)

**Formulas:**
```
YTM_after_tax = YTM_gross × (1 - 0.13) = YTM_gross × 0.87
real_yield = YTM_after_tax - broker_commission - spread - inflation
```

**Input:** bond_offering (YTM, price), optional market data (spread, inflation forecast)
**Output:**
```json
{
  "ytmGross": 15.5,
  "ytmAfterTax": 13.49,
  "brokerCommissionPct": 0.1,
  "spreadCostPct": 0.3,
  "inflationForecast": 8.0,
  "realYield": 5.09,
  "nkdImpact": "При покупке НКД 30₽ увеличивает реальную цену входа"
}
```

---

### 10. LiquidityAnalyzer

**File:** `src/analysis/bonds/liquidity_analyzer.py` (NEW)

Evaluates bond liquidity using concrete thresholds from market data:

| Metric | OFZ threshold | Corporate threshold |
|---|---|---|
| Daily volume (VALUE) | > 100M RUB (high), 20-50M (medium), < 500K (low) | > 1M RUB |
| Bid-ask spread | < 0.3% | < 1.0% |
| Trade count (NUMTRADES) | > 20/day | > 20/day |
| Order book depth | > 50 lots per side | > 10 lots per side |
| Amihud ratio | < 0.01 | < 0.1 |

**Data source:** `moex.get_marketdata()` — fields `NUMTRADES`, `VALTODAY`, `VOLTODAY`, `BID`, `ASK`, `BIDDEPTH`, `ASKDEPTH`, `WAPRICE`, `YIELD`

**MOEX endpoints:**
```
GET /iss/engines/stock/markets/bonds/boards/TQOB/securities/{security}/orderbook.json  → BID, ASK, DEPTH
GET /iss/engines/stock/markets/bonds/boards/TQOB/securities/{security}.json?iss.only=marketdata  → VALTODAY, NUMTRADES
GET /iss/engines/stock/markets/bonds/securities/{security}/candles.json  → для Amihud ratio
```

**Output:** `{"liquidityScore": "high"|"medium"|"low", "metrics": {"value": 50000000, "spread": 0.25, "numTrades": 45, ...}, "warnings": [...]}`

---

### 11. PutOptionValuator

**File:** `src/analysis/bonds/put_option_valuator.py` (NEW)

Quantifies the value of a put option (offer/call) on a bond:

**Formal definition:**
```
Option_value = P_putable − P_straight
```
где P_putable — цена облигации с офертой, P_straight — цена аналогичной без оферты.

**Price sensitivity WITHOUT put (линейная аппроксимация):**
```
ΔP/P ≈ −D_mod × Δr + 0.5 × C × (Δr)²
```
где D_mod = modified duration, C = convexity, Δr = change in yield.

**Важно:** при Δr < 50-100 б.п. выпуклостью можно пренебречь. При больших движениях convexity обязательна.

**Put value as insurance against rate hikes:**
```
put_protection = max(0, nominal_price − current_price)
```
При росте ставок на Δr:
- Без пута: цена падает на D × Δr × P
- С путом: инвестор предъявляет к выкупу по номиналу, убыток ограничен

**Стоимость «страховки» (цена пута в годовых):**
```
put_insurance_cost = YTM_equivalent_without_put − YTM_with_put
```
Пример: РЖД без пута даёт YTM 16%, с путом 14.8% → цена страховки = 1.2% годовых.

**Integrated in bond_signals.py:**
- In cutting cycle: put reduces value slightly (less need for insurance)
- In hiking cycle: put adds significant value (insurance against rate hikes)
- If has_offer AND rate_cycle == "hiking": score += put_value * weight

---

### 12. KellyPositionSizer

**File:** `src/analysis/bonds/kelly_position_sizer.py` (NEW)

Calculates optimal speculative position size using adapted Kelly criterion:

```
f* = [p·(1+r_spec) − (1-p)·(1-Recovery)] / (r_spec + Recovery)
```

Where:
- p = probability of no default (for BBB+ ~95-97%)
- r_spec = risk premium (YTM_speculative − YTM_risk_free)
- Recovery = recovery rate at default (30-50% for bonds)

**Practical correction for small portfolios (< 50K RUB):**
- Kelly often gives absurdly high values (68% for ПР-Лизинг)
- Cap at 10% for portfolios < 50K RUB, max 1 speculative position
- Cap at 20% for portfolios > 50K RUB

**Integrated in BondPortfolioOptimizer:**
- Uses Kelly to recommend position size for speculative bonds
- Applies caps based on portfolio size

---

### 13. RateCycleScenarioB

**File:** `src/analysis/bonds/rate_cycle_scenario_b.py` (NEW)

Alternative strategy for when rate doesn't drop as expected:

**Triggers for Scenario B:**
- ЦБ 2+ meetings in a row holds rate without cutting
- Inflation grows 3+ months
- Real rate (key rate − inflation) turns negative

**Actions:**
1. Reduce duration: sell long OFZ, buy OFZ 2027-2028 (26234, 26235)
2. Switch to floaters: OFZ-PK (coupon follows key rate)
3. Compare with deposits: if deposit rate > bond YTM → switch to deposits
4. Wait for better entry: hold in LQDT/deposit, buy long OFZ after sell-off

**Output:**
```json
{
  "scenarioBActive": true,
  "triggerReason": "ЦБ не снижает ставку 2+ заседания",
  "recommendations": [
    "sell": ["SU26238RMFS5", "SU26254RMFS5"],
    "buy": ["SU26234RMFS5", "SU26235RMFS5", "ОФЗ-ПК"]
  ],
  "expectedYieldImpact": "−2% to −3% vs main scenario"
}
```

**Integrated in:**
- `rate_cycle.py` — when hiking or prolonged stable, activate Scenario B
- Portfolio bonds API — show scenario B alongside main recommendation

---

### 14. RebalancingTriggerEngine

**File:** `src/analysis/bonds/rebalancing_triggers.py` (NEW)

Automated rebalancing rules:

| Trigger | Action |
|---|---|
| Key rate changes ±1.5% | Review duration exposure |
| Bond price changes ±15% | Check fundamentals (rating, news) |
| Bond matures / offer executed | Reinvest per target structure |
| Credit rating changes 1+ notch | Review position (sell below investment grade) |
| Quarterly calendar check | Verify target allocations (±5% deviation = rebalance) |

**Integrated in:**
- Portfolio bonds API — `rebalancingTriggers` field shows active triggers
- Alert engine — push notification when trigger fires

---

### 15. CreditRating Enhancement (DB model + collector)

**File:** `src/db/models/instrument.py` — BondOffering (MODIFY)
**File:** `src/collectors/moex.py` — add rating fields (MODIFY)

Add fields to BondOffering:
```python
rating_agency = Column(String(20))    # "ACRA" | "RAEX" | "NKR" | "broker_internal"
rating_date = Column(Date)             # дата присвоения/обновления
rating_scale = Column(String(10))     # "national" | "international"
```

MOEX ISS API has fields in `securities.json` or `list_securities`:
- `RATINGAGENCY`, `RATINGDATE`, `RATINGSCALE`
- Need to parse and store in BondOffering

**Also requires:** Alembic migration for new columns.

---

### 16. RealYieldCalculator

**File:** `src/analysis/bonds/real_yield.py` (NEW)

Calculates holistic real yield chain:
```
YTM_gross
  → YTM_after_tax = YTM_gross × 0.87 (13% НДФЛ)
    → YTM_after_costs = YTM_after_tax − broker_in_out − spread
      → Real yield = YTM_after_costs − inflation_forecast
```

**Integrated in:**
- Bond metrics API (`/api/instruments/{ticker}/metrics`) — add `realYield` field
- Bond analysis API (`/api/instruments/{ticker}/analysis`) — show real yield in pros/cons

---

### 17. DefaultProbabilityFetcher

**File:** `src/analysis/bonds/default_probability_fetcher.py` (NEW)

Парсинг historical default rates от рейтинговых агентств.

**Источники:**
- Эксперт РА: raexpert.ru/about/disclosure/default-level-data/ (PDF/Excel, каждое полугодие)
- АКРА: acra-ratings.ru → Раскрытие информации (PDF-отчёты)
- Cbonds: cbonds.ru → Статистика дефолтов (таблицы, авторизация)

**Output:**
```python
DEFAULT_RATES_BY_RATING = {
    "AAA": 0.001, "AA+": 0.003, ..., "BBB+": 0.07, "BBB": 0.10, ..., "B-": 0.25
}
```

**Данные 2025-2026:**
- АКРА 2025: 23 дефолта (3.2% эмитентов), без ЦФА: 2.8%
- Эксперт РА 2025: 20 дефолтов (рост 2x к 2024)
- Прогноз 2026: наиболее уязвимы BBB+ до B-

**Интеграция:** KellyPositionSizer получает актуальную p для рейтинга.

---

### 18. RecoveryRateModel

**File:** `src/analysis/bonds/recovery_rate_model.py` (NEW)

Recovery rate как функция параметров эмитента:

```python
recovery = f(сектор, рейтинг, госучастие, тип_дефолта, цикл_экономики)
```

**Данные ВШЭ (2002-2011, 59 дефолтов):**
| Тип дефолта | Средний recovery | Std dev |
|---|---|---|
| Неисполнение оферты | 47.0% | 21.2% |
| Невыплата номинала | 68.7% | 30.3% |
| Общий итог | 48.8% | 29.1% |

**С госучастием:** ~66.7%
**Без госучастия:** ~30-40% (уточнение второй модели: 35-45% → 30-40% из-за ухудшения макро 2022-2026)

**Для ПР-Лизинг (BBB+, лизинг, без госучастия):** 30-40%
**Коррекция 2025-2026:** снижение ликвидности активов, более длительные процедуры банкротства, ухудшение стоимости залогов.

---

### 19. InflationFetcher

**File:** `src/analysis/inflation_fetcher.py` (NEW)

Парсинг инфляции из открытых источников ЦБ РФ.

**Источники:**
- cbr.ru/hd_base/infl/ — фактическая инфляция (HTML/CSV, ежемесячно)
- cbr.ru/dkp/ — ДКП PDF с прогнозом инфляции (ежеквартально)
- economy.gov.ru — макропрогнозы Минэкономразвития

**Рекомендация:** хранить в БД историю прогнозов vs фактическая инфляция для оценки точности.

**Output:**
```json
{
  "currentInflation": 8.5,
  "cbrForecast": {"2026": 7.5, "2027": 5.0},
  "source": "cbr.ru/dkp/2026-q2",
  "updatedAt": "2026-07-01"
}
```

---

### 20. BrokerCommissionConfig

**File:** `src/constants.py` (MODIFY) + `src/trading/broker_commissions.py` (NEW)

Реальные комиссии брокеров из поиска:

```python
BROKER_COMMISSION_CONFIG = {
    "tbank": {"commission_pct": 0.025, "min_rub": 0, "monthly_fee": 0},
    "bcs": {"commission_pct": 0.03, "min_rub": 0, "monthly_fee": 299},
    "finam": {"commission_pct": 0.05, "min_rub": 50, "monthly_fee": 0},
    "vtb": {"commission_pct": 0.03, "min_rub": 0, "monthly_fee": 0},
    "alpha": {"commission_pct": 0.03, "min_rub": 0, "monthly_fee": 199},
    "otkritie": {"commission_pct": 0.03, "min_rub": 0, "monthly_fee": 0},
}
MOEX_EXCHANGE_FEE_PCT = 0.01
```

**Интеграция:** AfterTaxYieldCalculator использует комиссию из профиля пользователя (BrokerCredential).

---

### 21. DynamicSpreadFilter

**File:** `src/analysis/bonds/dynamic_spread_filter.py` (NEW)

Расчёт спреда из реальных данных MOEX ISS и динамический фильтр сделок.

**Формулы:**
```python
# Snapshot (текущий стакан)
spread_pct = (ASK - BID) / ((ASK + BID) / 2) * 100

# Средний за период (из минутных свечей)
spreads = [(high - low) / close * 100 for candle in candles]
avg_spread = mean(spreads)
```

**Пороги:**
| Тип | MAX_SPREAD |
|---|---|
| ОФЗ | 0.3% |
| AAA корпоративные | 0.5% |
| A корпоративные | 1.0% |
| BBB+ и ниже | 2.0% |

**Логика:** `if spread > MAX_SPREAD_PCT: reject_trade(f"Спред {spread}% > лимита {MAX_SPREAD_PCT}%")`

**MOEX endpoint:** `GET /iss/engines/stock/markets/bonds/boards/{board}/securities/{security}/orderbook.json`
Board: TQOB (основной), TQCB (корпоративные)

---

### 22. TaxCalculatorLDV

**File:** `src/analysis/tax_calculator.py` (NEW)

Расчёт налога с учётом типа счета и ЛДВ.

| Тип счёта | Налог на купоны | Налог на продажу | Особенности |
|---|---|---|---|
| Брокерский | 13% | 13%, ЛДВ 3+ года на CapGain | LDV освобождает прирост капитала |
| ИИС-1 (закрыт) | 13% | 13% | Вычет на взнос |
| ИИС-2 (закрыт) | 13% | 0% на доход | Льгота по доходу |
| ИИС-3 | 13% | 13% на продажу | Вычет до 52K/год, ЛДВ работает |

**Формула для облигаций с учётом ЛДВ:**
```
YTM_after_tax = (Coupon_income × 0.87 + Capital_gain × 1.0) / Average_investment
```
где Capital_gain = цена погашения/продажи − цена покупки (освобождается при ЛДВ 3+ года).

**Важно:** ЛДВ освобождает от налога на прирост капитала, НЕ освобождает от налога на купонный доход.

---

### 23. MacroScenarioEngine

**File:** `src/analysis/macro_scenario_engine.py` (NEW)

Полная матрица макро-сценариев с автоматическим детектором.

**Сценарии:**

| Сценарий | Ставка ЦБ | Инфляция | Стратегия | Дюрация | Триггер |
|---|---|---|---|---|---|
| **A: Мягкая посадка** | 21%→12-13% | 8%→5% | Длинные ОФЗ, корп среднего риска | 5-7 лет | Базовый |
| **B: Стагнация** | 21%±1% 12+мес | 8-10% | Флоатеры, короткие (<2л), депозиты | <2 года | 2 заседания без снижения |
| **C: Кризис/рецессия** | 21%→8% за 6мес | 3-4% | Макс дюрация, длинные ОФЗ, zero-купон | 10+ лет | 2 заседания подряд снижение ≥1% |

**⚠️ Вторая модель: сценарий C крайне маловероятен для РФ.**
- 13 п.п. снижения за 6 мес не имеет прецедентов
- **Использовать только для стресс-тестов, не как базовый прогноз**
- Реалистичный сценарий снижения: 21% → 15-17% за 12-18 мес
| **D: Санкции** | — | — | Только ОФЗ + квази-гос, избегать корп с иностр связями | Любая | Санкционные события |
| **E: Волна дефолтов** | — | — | Бегство в качество, только ОФЗ+AAA | Короткая | 5+ дефолтов/квартал среди BBB+ |

**Детекция сценария:**
```python
def detect_scenario(key_rate_history, inflation_history, default_count_quarterly, sanctions_events):
    if sanctions_events:
        return "D"
    if default_count_quarterly >= 5:
        return "E"
    if key_rate dropped >= 1% in 2 consecutive meetings:
        return "C"
    if key_rate unchanged for 2+ meetings AND inflation > 8%:
        return "B"
    return "A"
```

**Интеграция:** PortfolioOptimiser использует сценарий для целевой структуры.

---

### 24. FXExposureModule

**File:** `src/analysis/fx_exposure.py` (NEW)

Расчёт валютной переоценки для замещающих облигаций (будущее расширение).

**Формула:**
```
Real_return = (1 + YTM_local) × (1 + ΔFX) − 1
```
где ΔFX — изменение курса валюты за период.

**Пример:** евробонд с YTM 8%, рубль ослабляет на 15%:
```
Real_return = 1.08 × 1.15 − 1 = 24.2%
```

**Использование:** пока портфель только в рублях — неактуально. Добавить в roadmap если появятся замещающие облигации.

---

### 25. MOEX Board Configuration

**File:** `src/collectors/moex.py` (MODIFY)

Board ID для облигаций в MOEX ISS:
- `TQOB` — основной рынок облигаций (Т+)
- `TQCB` — корпоративные облигации

**Новые endpoint'ы для ликвидности:**
```
GET /iss/engines/stock/markets/bonds/boards/{board}/securities/{security}/orderbook.json
  → BID, ASK, BIDDEPTH, ASKDEPTH, NUMBIDS, NUMASKS

GET /iss/engines/stock/markets/bonds/boards/{board}/securities/{security}.json?iss.only=marketdata
  → VALTODAY, VOLTODAY, NUMTRADES, LAST, LASTCHANGE

GET /iss/engines/stock/markets/bonds/securities/{security}/candles.json?interval=24
  → для расчёта Amihud ratio
```

**Важно:** реальные данные стакана требуют подписки на реалтайм. Робот получает 15-минутную задержку бесплатно.

---

## Implementation Priority

### Phase 1 (Critical — done ✅)
- [x] DefaultRiskImpactAnalyzer
- [x] RateCycleAwareStrategy + bond_signals.py modification
- [x] Bond portfolio constants
- [x] BondPortfolioOptimizer
- [x] Extended portfolio bonds API
- [x] Enhanced bond analysis API
- [x] BondLadderGenerator

### Phase 2 (Critical v2 — model honesty review) ✅
- [x] AfterTaxYieldCalculator (НКД + налоги)
- [x] LiquidityAnalyzer
- [x] PutOptionValuator
- [x] KellyPositionSizer
- [x] RateCycleScenarioB
- [x] RebalancingTriggerEngine
- [x] CreditRating model enhancement (agency, date, scale)
- [x] RealYieldCalculator
- [x] TaxCalculatorLDV (учёт типа счёта и ЛДВ)
- [x] BrokerCommissionConfig (конфиг реальных комиссий)

### Phase 3 (Data quality — точные цифры взамен эвристик) ✅
- [x] DefaultProbabilityFetcher (парсинг АКРА/Эксперт РА)
- [x] RecoveryRateModel (recovery = f(сектор, рейтинг, госучастие))
- [x] InflationFetcher (cbr.ru парсинг факта + прогноза)
- [x] DynamicSpreadFilter (спред из MOEX, reject trade если выше порога)
- [x] MacroScenarioEngine (полная матрица A/B/C/D/E)
- [x] MOEX collector: rating agency/date/scale
- [x] MOEX collector: orderbook + marketdata для ликвидности
- [x] Alembic migration: rating_agency, rating_date, rating_scale

### Phase 4 (Polish & Future) ✅
- [x] FXExposureModule (валютная переоценка — будущее)
- [x] Frontend updates (Next.js)
- [x] Test coverage for all modules

---

## Key Principle Changes

| Principle | Current finn-help | Target |
|---|---|---|
| Bond analysis scope | Single bond | Entire portfolio context |
| Duration risk judgment | Always penalize long | Penalize only in hiking, bonus in cutting |
| Floaters | Always good (protection) | Good in hiking, bad in cutting |
| Credit rating | Numeric score | Split by investment grade vs speculative |
| Position sizing | Based on signal only | Based on rating + portfolio size + concentration |
| Default risk | None | Quantified "months to recover" metric |
| Macro for bonds | Generic macro thresholds | Rate cycle direction specific to bonds |
| Liquidity/ETF role | None (just another position) | Defined role as liquidity buffer |
| НКД и налоги | Ignored | YTM × 0.87 − комиссия − спред − инфляция |
| Ликвидность | Qualitative only | Measured: volume, spread, depth, Amihud ratio |
| Put-опцион | +0.05 (flat bonus) | ΔP ≈ −D × Δr × P; valued higher in hiking cycle |
| Спекулятивный вес | Heuristic 5-10% | Kelly formula f\* = [p·(1+r) − (1-p)·(1-R)] / (r+R), capped by portfolio size |
| Rate scenario planning | Single scenario (rate drops) | Scenario B: rate hikes/stays → duration↓, floaters, deposits |
| Rebalancing | Manual | Automatic triggers: ±1.5% rate, ±15% price, maturity, rating change, quarterly |
| Credit rating metadata | Just a string | Agency (ACRA/RAEX/NKR), date, scale (national/international) |
| Real yield | YTM only | YTM_after_tax − costs − inflation |
| Default probability (p) | Heuristic 96% for BBB+ | Actual: 90-93% (АКРА/Эксперт РА парсинг) |
| Recovery rate | Heuristic 40% | f(сектор, рейтинг, госучастие, тип дефолта); с гос ~66.7%, без ~35-45% |
| Broker commission | 0.05% flat | Per broker config: Т-Банк 0.025%, БКС 0.03%, MOEX 0.01% |
| Spread filter | None | Dynamic: ASK-BID from MOEX orderbook; reject if > threshold |
| Tax with LDV | 13% on everything | (Coupon×0.87 + CapGain×1.0) / AvgInv при ЛДВ 3+ года |
| Macro scenarios | A (rate drops) only | A/B/C/D/E with automatic detection |
| Inflation forecast | Not fetched | cbr.ru парсинг: ДКП PDF (прогноз) + hd_base (факт) |
| Liquidity data source | Qualitative only | MOEX orderbook.json + marketdata + candles |
| FX exposure | Ignored | (1+YTM)×(1+ΔFX)−1 (для будущих евробондов) |
| Board config for MOEX | No bond-specific boards | TQOB (main), TQCB (corporate) |
| YTM solver | Newton-Raphson | Гибрид: NR → Brent fallback |
| ΔP formula | −D×Δr | −D×Δr + 0.5×C×(Δr)² при Δr > 50-100 б.п. |
| Put valuation | Qualitative | Option = P_putable − P_straight |
| Amortization duration | Упрощённо | Полный график всех потоков, нет упрощения |
| Cycle indicators | Key rate only | Core CPI, RUONIA, short OFZ, ЦБ rhetoric (LLM) |
| Scenario C | Моделировался как базовый | Только для стресс-тестов |
| VALUE liquidity thresholds | 1M/10M heuristic | 500K low, 20-50M medium, 100M+ high |

---

## Files to Create (Phase 1 — done)

| File | Purpose | Status |
|---|---|---|
| `src/analysis/bonds/default_risk_analyzer.py` | Default impact calculation per position | ✅ |
| `src/analysis/bonds/rate_cycle.py` | Rate cycle detection | ✅ |
| `src/analysis/bonds/bond_portfolio_optimizer.py` | Portfolio-level optimization | ✅ |
| `src/analysis/bonds/bond_ladder_generator.py` | Maturity ladder generation | ✅ |

## Files to Create (Phase 2 — done ✅)

| File | Purpose | Status |
|---|---|---|
| `src/analysis/bonds/after_tax_yield.py` | НКД + налог 13% + реальная доходность | ✅ |
| `src/analysis/bonds/liquidity_analyzer.py` | Ликвидность по метрикам (объём, спред, глубина) | ✅ |
| `src/analysis/bonds/put_option_valuator.py` | Количественная оценка стоимости пута | ✅ |
| `src/analysis/bonds/kelly_position_sizer.py` | Формула Келли для спекулятивных позиций | ✅ |
| `src/analysis/bonds/rate_cycle_scenario_b.py` | Стратегия B — ставка не снижается | ✅ |
| `src/analysis/bonds/rebalancing_triggers.py` | Автоматические триггеры ребалансировки | ✅ |
| `src/analysis/bonds/real_yield.py` | Сквозной расчёт реальной доходности | ✅ |
| `src/analysis/tax_calculator.py` | Расчёт налога с учётом типа счёта и ЛДВ | ✅ |
| `src/trading/broker_commissions.py` | Конфиг реальных комиссий брокеров | ✅ |

## Files to Create (Phase 3 — data quality) ✅

| File | Purpose | Status |
|---|---|---|
| `src/analysis/bonds/default_probability_fetcher.py` | Парсинг default rates АКРА/Эксперт РА (PDF/Excel) | ✅ |
| `src/analysis/bonds/recovery_rate_model.py` | Recovery = f(сектор, рейтинг, госучастие) | ✅ |
| `src/analysis/inflation_fetcher.py` | Парсинг инфляции cbr.ru (факт + ДКП прогноз) | ✅ |
| `src/analysis/bonds/dynamic_spread_filter.py` | Спред из MOEX orderbook, reject trade если выше порога | ✅ |
| `src/analysis/macro_scenario_engine.py` | Полная матрица A/B/C/D/E с детекцией | ✅ |
| `src/analysis/fx_exposure.py` | Валютная переоценка для будущих евробондов | ✅ |

## Files to Modify (Phase 1 — done ✅)

| File | Changes | Status |
|---|---|---|
| `src/analysis/signals/bond_signals.py` | Rate cycle awareness, portfolio context | ✅ |
| `src/signals/engine.py` | Pass rate cycle to bond analysis | ✅ |
| `src/constants.py` | Bond portfolio rules, rating categories | ✅ |
| `src/interfaces/api/routes/portfolio_bonds.py` | Default impact, ladder, rate cycle, health | ✅ |
| `src/interfaces/api/routes/bonds.py` | Portfolio context in analysis | ✅ |

## Files to Modify (Phase 2/3 — done ✅)

| File | Changes | Phase | Status |
|---|---|---|---|
| `src/db/models/instrument.py` (BondOffering) | Add rating_agency, rating_date, rating_scale | 2 | ✅ |
| `src/collectors/moex.py` | Parse rating agency/date/scale from MOEX ISS; add orderbook/marketdata endpoints | 3 | ✅ |
| `src/analysis/bonds_math.py` | ytm_solver: гибрид Newton-Raphson + Brent; compute_modified_duration: полный график потоков для амортизации | 2 | ✅ |
| `src/analysis/bonds/rate_cycle.py` | Добавить индикаторы: RUONIA, короткий конец ОФЗ, риторика ЦБ | 2 | ✅ |
| `src/interfaces/api/routes/bonds.py` | Add realYield, liquidityScore, dynamic spread to metrics/analysis | 2 | ✅ |
| `src/interfaces/api/routes/portfolio_bonds.py` | Add scenarioB, rebalancing triggers, macroScenario | 2 | ✅ |
| `src/constants.py` | Add BROKER_COMMISSION_CONFIG, MOEX_BOARDS, SPREAD_THRESHOLDS | 2 | ✅ |
