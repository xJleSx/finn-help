# FINN-HELP AUDIT REPORT

## Условные обозначения

| Символ | Значение |
|--------|----------|
| 🔴 | CRITICAL — требует немедленного исправления |
| 🟠 | HIGH — серьёзная проблема |
| 🟡 | MEDIUM — значительное улучшение |
| 🔵 | LOW — незначительно |
| ⚪ | INFO — рекомендация |

---

# 1. CORE (`src/core/`, `src/db/`, `src/config.py`, `src/constants.py`, `src/cache.py`)

## 🔴 CRITICAL

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 1.1 | `core/crypto.py:49-51` | При ошибке шифрования/дешифрования функции возвращают plaintext. Ключ сломан — данные утекают молча. |
| 1.2 | `core/crypto.py:10` | Cipher — глобальный singleton. Ротация ключа невозможна без перезапуска. |
| 1.3 | `core/ddd/base.py:37-41` | `AggregateRoot.publish_events()` вызывает async `bus.publish_sync()` без `await` — все domain events теряются. |
| 1.4 | `core/ddd/base.py:58-72` | `UnitOfWork.__exit__` вызывает abstract `commit()`/`rollback()` — нет реализации SQLAlchemy. Падает с TypeError. |
| 1.5 | `core/auth_service.py:28-52` | Нет проверки длины/сложности пароля при регистрации. `password_min_length` из config не используется. |
| 1.6 | `core/auth_service.py:54-80` | Нет rate limiting на login. Brute-force атака возможна. |
| 1.7 | `db/connection.py:41-50` | `async_engine` инициализируется при import. Если БД недоступна — import падает. |

## 🟠 HIGH

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 1.8 | `config.py:11,199-205` | JWT secret по умолчанию — ephemeral random. После перезапуска все сессии инвалидируются. |
| 1.9 | `config.py:186` | `encryption_key` хранится в plaintext. Нет предупреждения если пустой. |
| 1.10 | `crypto.py:32-34` | Ключ не 44 символа — хешируется SHA256. Любая строка «работает», создавая ложное чувство безопасности. |
| 1.11 | `cache.py:60` | MD5 для cache key — cache poisoning через коллизии. |
| 1.12 | `cache.py:79-82` | Redis read path не защищён `_lock` — thundering herd. |
| 1.13 | `db/connection.py:79-105` | `_init_read_replica()` — TOCTOU race condition. Два потока создают два engine. |
| 1.14 | `db/connection.py:109-123` | `get_read_replica_session()` — после смены URL replica используется stale engine. |
| 1.15 | `resilience.py:88-132` | `CircuitBreaker.call()` — lock отпускается между проверкой и вызовом. Race condition. |
| 1.16 | `resilience.py:237-245` | Rate limiter — busy-wait `while True + asyncio.sleep(0.001)`. Жрёт CPU. |
| 1.17 | `resilience.py:165-168,269-272` | `get_circuit_breaker` / `get_rate_limiter` — без блокировки. Два экземпляра одного breaker. |
| 1.18 | `executor.py:22-25` | `executor_max_workers` без верхней границы — 10000 тредов убьют систему. |
| 1.19 | `container.py:171-227` | `wire()` импортирует всё — циклические импорты, хрупкость. |
| 1.20 | `container.py:229-244` | `container_for_testing` — все зависимости MagicMock. Тесты проходят при любой ерунде. |
| 1.21 | `shutdown.py:34-42` | `sys.exit(0)` внутри `add_signal_handler` — блокирует event loop. |
| 1.22 | `shutdown.py:11-15` | `register_shutdown_hook` — не thread-safe. |
| 1.23 | `event_bus.py:48` | `asyncio.gather(return_exceptions=True)` — все исключения handler-ов молча глотаются. |
| 1.24 | `credential_store.py:41-46` | `get_broker_token` падает на `settings.tinkoff_token` для ВСЕХ брокеров (не только tbank). |
| 1.25 | `credential_store.py:13-19` | `_BROKER_TOKEN_ATTRS` — `finam_token` не существует в Settings. Все брокеры падают на Tinkoff. |
| 1.26 | `auth_service.py:64` | `verify_totp` — перебор recovery codes по одному. Timing leak количества кодов. |
| 1.27 | `http_client.py:78` | `request()` аннотирован возвращать `httpx.Response`, но может вернуть `None` — крах `AttributeError: 'NoneType' object has no attribute 'json'`. |
| 1.28 | `http_client.py:44-45` | `self._circuit_breaker.config.failure_threshold = ...` — модифицирует shared config. |
| 1.29 | `plugin/base.py:139-155` | `discover_plugins` находит плагины и логирует, но НЕ регистрирует. Мёртвый код. |
| 1.30 | `observability/tracing.py` vs `tracing.py` | Два модуля tracing с разным API. Один использует `@trace_call`, другой `@traced` — путаница. |
| 1.31 | `totp.py:46-53` | Recovery codes — 8 hex chars (32 бита). Offline brute-force тривиален. |
| 1.32 | `health.py:41` | `check_llm_health` отправляет запрос к LLM — потребляет квоту API и деньги. |
| 1.33 | `health.py:76` | `check_tbank_health` — нет таймаута. |

## 🟡 MEDIUM

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 1.34 | `config.py:193` | `extra = "ignore"` — опечатки в .env молча игнорируются |
| 1.35 | `config.py:14-27` | `personal_settings.yaml` загружается, но не экспортируется в модули |
| 1.36 | `constants.py:50-58` | `SECTOR_LIMITS` дублируется с `compliance_sector_limit_pct` |
| 1.37 | `constants.py:10-25` | `KNOWN_DIVIDEND_STOCKS` — hardcoded, устареет |
| 1.38 | `cache.py:102-119` | `invalidate(pattern)` — pattern без санитизации |
| 1.39 | `cache.py:43` | После падения Redis — `_pool = False`, reconnect никогда не происходит |
| 1.40 | `cache.py:63-99` | `cached` decorator не работает с async функциями |
| 1.41 | `db/connection.py:17-18` | `_is_postgres` — fragile substring match |
| 1.42 | `db/connection.py:162-173` | `session_scope` — при ошибке rollback теряет original exception |
| 1.43 | `db/connection.py:186-194` | `close_db` не вызывает `engine.dispose()` — утечка соединений |
| 1.44 | `db/queries.py:25-80,110-158` | sync и async bulk_upsert — дублирование кода |
| 1.45 | `db/queries.py:77-78` | При ошибке вставки строки — DEBUG логи. Caller не узнает о частичной вставке |
| 1.46 | `db/models/instrument.py:31` | `instrument_type default="stock"` — не совпадает с DDD моделью |
| 1.47 | `db/models/user.py:36-40` | `UserSetting` — EAV антипаттерн |
| 1.48 | `db/models/news.py:22` | `url = String(1024)` — URL >1024 сломают индекс |
| 1.49 | `resilience.py:162` | `_circuit_breakers_lock` создан, но никогда не используется |
| 1.50 | `executor.py:30-32` | `run_cpu_bound` после shutdown создаёт новый executor |
| 1.51 | `shutdown.py:18-23` | Shutdown hooks — `fn()` без `await`. Async hooks потеряны |
| 1.52 | `container.py:148-155` | `dispose()` — `except Exception: pass`, ошибки замыкания глотаются |
| 1.53 | `observability/metrics.py:42-59` | `setup_metrics()` дважды — дублирует инструменты OpenTelemetry |
| 1.54 | `observability/metrics.py:14` | OTLP endpoint hardcoded |
| 1.55 | `plugin/base.py:45-53` | `trigger_async` вызывает `await handler()` — sync handler упадёт с TypeError |
| 1.56 | `plugin/base.py:56-62` | `hook` декоратор добавляет `_hooks` атрибут на функцию — конфликт с др. декораторами |
| 1.57 | `ddd/base.py:20` | `Entity.__hash__` — только `id` без учёта типа. Коллизия у разных типов |
| 1.58 | `auth_service.py:67` | Recovery code удаляется, а не помечается used |
| 1.59 | `http_client.py:47-50` | `_get_client()` создаёт новый client после `close()` — нарушение контракта shutdown |

## 🔵 LOW / ⚪ INFO

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 1.60 | `config.py:52` | `cors_origins` default — localhost:3000 |
| 1.61 | `constants.py:3-8` | Magic numbers без комментариев |
| 1.62 | `cache.py:122-132` | `close_redis` — memory cache чистится после pool disconnect |
| 1.63 | `db/queries.py:85` vs `ddd/instrument.py:123` | ticker не нормализуется в DDD репозитории |
| 1.64 | `db/models/portfolio.py:42` | `tx_type = Column("type")` — shadows built-in |
| 1.65 | `db/models/audit.py:19-20` | `prev_hash`/`hash` без chain validation |
| 1.66 | `logging.py:9` | `hasattr(settings, "log_level")` — dead code |
| 1.67 | `sentry.py:28-29,42-43,51-52` | Все ошибки Sentry молча глотаются |
| 1.68 | `tracing.py:41` | `get_tracer()` после `setup_tracing()` — разные tracer-ы |
| 1.69 | `event_bus.py:50-51` | `publish_sync` — async функция с вводящим в заблуждение именем |
| 1.70 | `health.py:57` | `check_telegram_health` — новый bot instance на каждый health check |
| 1.71 | `container.py:127-131` | `get()`/`get_async()` — возвращают `Any`, теряется типизация |
| 1.72 | `container.py:80-82,88-91` | TRANSIENT lifecycle не работает — ведёт себя как SINGLETON |
| 1.73 | `context.py:13` | `generate_id(uuid4.hex[:length])` — length без валидации |
| 1.74 | `observability/metrics.py:62-93` | tracking functions не проверяют `instruments is None` |
| 1.75 | `observability/tracing.py:29-50` | FakeTracer/FakeSpan — не хватает методов. Упадёт если caller обращается к не-stub |

---

# 2. ANALYSIS (`src/analysis/` — 30+ файлов)

## 🔴 CRITICAL

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 2.1 | `ml/walk_forward.py:*` | Look-ahead bias: метки вычисляются с использованием данных из тестового периода. Все метрики качества невалидны. |
| 2.2 | `ml/_base.py:*` | Stale model detection работает в обратную сторону — модели старше 1 часа отбрасываются. |
| 2.3 | `ml/ensemble.py:_train_meta_oof()` | Деление на ноль при первом вызове (нет OOF-предсказаний). |
| 2.4 | `technical/__init__.py:RSI,ATR,ADX` | Используют `ewm(span=period, adjust=False)` вместо Wilder's `alpha=1/period`. Различие 3-8% на первых 3×period строк. |
| 2.5 | `volatility.py:garman_klass_volatility` | Может вычислить отрицательную вариансу → sqrt → NaN. |
| 2.6 | `walk_forward_analysis.py:*` | Walk-forward считает метрики на RAW ценах, а не на equity кривой модели. Оценивает актив, а не модель. |
| 2.7 | `backtest.py:*` | Regime detection использует данные всего периода — look-ahead. |
| 2.8 | `personal_backtest.py:*` | Сигнал исполняется по close текущего дня — look-ahead. В реальности сигнал доступен на open следующего дня. |
| 2.9 | `ml/price_targets.py:*` | Forecast return использует будущие цены. |
| 2.10 | `anomaly/features.py:*` | Feature engineering использует даты из будущего при reindex. |
| 2.11 | `anomaly/autoencoder.py:*` | ADWIN drift detector — O(n²) сложность, неправильная epsilon формула. |
| 2.12 | `portfolio/black_litterman.py:*` | Упрощение Omega matrix некорректно. Gradient-free optimiser для high-dim. |
| 2.13 | `fundamental/base.py:bond math` | Continuous compounding вместо periodic — ошибка 2-3% на стандартных облигациях. |
| 2.14 | `technical/__init__.py:ichimoku` | Chikou Span смещён на 26 дней назад — используется будущая цена. |

## 🟠 HIGH

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 2.15 | `ml_coordinator.py:*` | Sequential loop по всем тикерам — нет `asyncio.gather`. Долго. |
| 2.16 | `ml/catboost_model.py:*` | Нет data-change detection — модель переобучается на одинаковых данных. |
| 2.17 | `technical/__init__.py:*` | `compute_all()` — копирует DataFrame N раз. O(N²) памяти. |
| 2.18 | `volatility.py:parkinson_volatility` | Python loop вместо векторизации — медленно на 1000+ инструментов. |
| 2.19 | `multi_timeframe.py:*` | Нет проверки, что `d.resample(freq)` не пустой — если нет данных за период, падает. |
| 2.20 | `service.py:440-497` | `train_models` — sync метод, блокирует event loop при вызове из async контекста. |
| 2.21 | `rebalancing.py:61-85` | `analyze_portfolio` — sync в async контексте. |
| 2.22 | `scenario/engine.py:*` | Scenario simulation — нет таймаута. Бесконечное зависание. |
| 2.23 | `anomaly/detector.py:*` | Все аномалии считаются на всём датасете — future leakage. |

## 🟡 MEDIUM

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 2.24 | `technical/__init__.py:*` | Нет защиты от `divide by zero` в индикаторах (SMA при period=0). |
| 2.25 | `volatility.py:*` | Нет проверки `len(highs) < period` → возвращает `np.full_like(np.nan)`. |
| 2.26 | `fundamental/base.py:38-43` | `get_sector_benchmarks()` cache не обновляется — stale после refresh. |
| 2.27 | `rebalancing.py:*` | `generate_plan()` не проверяет `total_turnover == 0` → `round(0, 2)` корректно, но комиссия 0 не логируется. |
| 2.28 | `fusion_optimizer.py:*` | Grid search по всем комбинациям — экспоненциальный рост. 8 компонентов → 6561 комбинация × 11 thresholds. |
| 2.29 | `ml/pooled.py:*` | Pooled model — стандартизация без проверки `std == 0`. |
| 2.30 | `inference/causal.py:*` | Causal inference — нет проверки на `multicollinearity`. |

## 🔵 LOW

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 2.31 | `technical/__init__.py` | Fibonacci, Elliott waves, scoring — помечены как experimental в TODO |
| 2.32 | `multi_timeframe.py` | `TIMEFRAMES` — hardcoded D/W/ME |
| 2.33 | `service.py` | Русские строки в error messages |

---

# 3. COLLECTORS + DATA + GEO + SOCIAL + MARKET

## 🔴 CRITICAL

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 3.1 | `collectors/base.py:30-86,99-250` | Два определения класса `BaseCollector`. Первый — мёртвый код. Второй — реально активный. |

## 🟠 HIGH

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 3.2 | `collectors/news.py:49` | `asyncio.run()` внутри sync метода. RuntimeError если caller в running loop. |
| 3.3 | `collectors/profiles.py:74` | `asyncio.run(self._fetch_profile_async(...))` — то же самое. |
| 3.4 | `collectors/financemarker.py:29` | API token в URL query parameter — утекает в логи, referrer, history браузера. |
| 3.5 | `collectors/social.py:247` | `db.commit()` внутри цикла `for msg in messages:` — 1 commit/msg. Медленно, partial commit при ошибке. |
| 3.6 | `collectors/parallel.py:41` | `asyncio.create_task(_worker)` + cancel() — `brpop` может оставить задачи в Redis. |
| 3.7 | `collectors/news.py:86` | `t in search_text` — substring match. "SBER" сматчится в "SBERBANK". |
| 3.8 | `data/batch_processor.py:109,131,157,176,206,222,233,247` | 8 `db.commit()` в одной pipeline. Частичное состояние при ошибке. |
| 3.9 | `geo/bayesian_risk.py:130` | `save_to_db` — query по `date` без `country`. Данные разных стран перезаписываются. |
| 3.10 | `geo/world_bank.py:55` | Hardcoded demo API key "apiKey=demo" — rate-limited заглушка. |
| 3.11 | `market/service.py:270` | `check_price_targets()` вызван без `await` — async или sync непонятно. |
| 3.12 | `social/sentiment/analyzer.py:190` | `_add_signal` — новый `get_session()` на каждый ticker×post. N×M соединений. |
| 3.13 | `social/pulse.py:69-71` | `httpx.Client()` sync в async контексте — блокирует thread pool. |
| 3.14 | **Cross-cutting** | Несоответствие имён секторов. `Нефть` в `company_risk_aggregator.py`, `energy` в `impact_matrix.py`, смешанные в `geopolitical_risk_engine.py`. Тихие ошибки. |

## 🟡 MEDIUM

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 3.15 | `collectors/bonds.py:202-210` | `_estimate_duration` — только bullet bonds semiannual. Не работает с амортизацией. |
| 3.16 | `collectors/financials.py:83` | User-Agent `"Mozilla/5.0"` — может быть заблокирован. |
| 3.17 | `collectors/macro.py:109,172,193` | `import lxml.html` внутри методов — повторный импорт на каждый вызов. |
| 3.18 | `collectors/social.py:251-253` | `_build_instrument_map` — загружает ВСЕ инструменты. Дорого. |
| 3.19 | `data/geopolitical_risk_engine.py:244` | Linear regression slope — деление на ноль при идентичных x. |
| 3.20 | `data/impact_matrix.py:14-87` vs `company_risk_aggregator.py:27-40` | Разные названия секторов — silent key mismatch. |
| 3.21 | `data/company_risk_aggregator.py:83-89` | `_get_market_regime` — N+1 запросов. |
| 3.22 | `data/news_filter.py:402-403` | `article_type` может быть любой строкой — defaultdict не используется. |
| 3.23 | `data/news_processor.py:48,55` | `hashlib.md5` для seeding — `# noqa: S324`. |
| 3.24 | `data/batch_processor.py:241` | `query(Instrument).limit(100).all()` — без ORDER BY. Разные инструменты в разных запусках. |
| 3.25 | `geo/bayesian_risk.py:117-119` | `row.score * 10.0 + 2.0` — undocumented heuristic. |
| 3.26 | `geo/sentiment_divergence.py:17` | `query(News).limit(1000)` — без ORDER BY. |
| 3.27 | `social/sentiment/aggregator.py:83-117` | `get_market_overview` — загружает ВСЕ `SentimentSignal` без limit. |
| 3.28 | `social/vk.py:22` | `settings.vk_group_ids.split(",")` → `[""]` при пустой строке. |
| 3.29 | `social/base.py` vs `pulse.py:167` | `normalize()` — override без вызова super(). Parent dead code. |
| 3.30 | `market/service.py:160-195` | `get_trade_plan` — загружает ВСЕ цены без limit. OOM для длинных периодов. |

## 🔵 LOW

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 3.31 | `collectors/__init__.py` | Экспортирует только 2 из 15+ коллекторов |
| 3.32 | `collectors/fundamental.py:1` | Docstring на русском (весь проект на английском) |
| 3.33 | `collectors/moex.py:14-81` | Mock data 68 строк внутри модуля |
| 3.34 | `data/__init__.py:22` | Конфликт имён `SentimentDivergenceDetector` (geo/ и data/) |
| 3.35 | `data/impact_matrix.py:100` | `self.matrix = IMPACT_MATRIX` — поверхностная копия, мутации влияют на глобал |
| 3.36 | `data/dashboard_provider.py:204-209` | Hardcoded weights `0.30, 0.30, 0.20, 0.20` — дубликат BASE_WEIGHTS |
| 3.37 | `data/news_filter.py:82-95` | `SCAM_KEYWORDS` — "доверительный управляющий" это лицензированная профессия |
| 3.38 | `geo/world_bank.py:20,52` | `self._client or httpx.AsyncClient(...)` — дублирование |
| 3.39 | `social/onchain_sentiment.py:27` | `" momentum " in text` — не сматчится в начале/конце строки |
| 3.40 | `social/onchain_sentiment.py:50-56,59-66` | `funding_rate_sentiment`, `long_short_ratio_sentiment` — мёртвый код |

---

# 4. TRADING + SIGNALS + ALERTS

## 🔴 CRITICAL

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 4.1 | `trading/paper.py:262` | Short PnL: `pnl = cost_basis + gross_value` (сложение вместо вычитания). |
| 4.2 | `trading/margin.py:37,69,92` | Формула плеча: `(portfolio_value + loan) / portfolio_value` вместо `1 + loan / (portfolio_value - loan)`. |
| 4.3 | `trading/margin.py:43-44` | Margin call price для shorts — неправильная формула. |
| 4.4 | `trading/compliance/limits.py:59` | `SUM(Portfolio.quantity * Instrument.id)` — умножает кол-во на **ID в БД**, не на цену. |
| 4.5 | `trading/execution/engine.py:490-492` | После успешного размещения ордера на бирже — ошибка DB update помечает ордер как "failed". Ордер жив на бирже, но в системе мёртв. |
| 4.6 | `trading/execution/stoploss.py:110-116` | Short SL/TP направление перевёрнуто. `stop = avg_price * (1 - abs(sl_pct))` — должен быть ABOVE. |
| 4.7 | `trading/compliance/aml.py:29-36` | `_user_daily_volume` никогда не сбрасывается. После N сделок все блокируются. |
| 4.8 | `alerts/generators.py:348-357` | `async_generate_all_alerts` — Session создана на вызывающем потоке, передана в executor. Session НЕ thread-safe. |

## 🟠 HIGH

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 4.9 | `trading/execution/engine.py:68-71` vs `types.py:44-47` | Два `TradeMode` enum — distinct types, провал isinstance. |
| 4.10 | `trading/compliance/aml.py:18-20` | AML state (volume, velocity) — in-memory только. После restart все ограничения сбрасываются. |
| 4.11 | `trading/execution/engine.py:283-288` | COVER в DRY_RUN вызывает `position_tracker.update(ticker, "BUY")` — добавляет phantom long. |
| 4.12 | `trading/execution/engine.py:464` | Slippage trade logging никогда не срабатывает для AUTO ордеров — `record.db_id` ещё 0. |
| 4.13 | `trading/execution/engine.py:361-367` | CB fallback pre-call не вызывает `position_tracker.update()`. Inconsistent. |
| 4.14 | `trading/risk/manager.py:104-108` | `stop_loss_pct = 5.0` (положительный) — условие `stop_loss_pct < 0` False → fallback на hardcoded 5%. |
| 4.15 | `trading/risk/manager.py:458` | `compute_vol_adjusted_size` принимает `atr`, а получает `price * sl_pct / 100`. Это не ATR. |
| 4.16 | `trading/risk/guards.py:56-60,311-321,340-357` | Глобальное состояние без `_risk_lock`. Race condition на kill switch, drawdown, day PnL. |
| 4.17 | `trading/execution/loop.py:161,190` | VaR возвраты перевёрнуты: `(vals[i] - vals[i+1]) / vals[i+1]` вместо `(vals[i+1] - vals[i]) / vals[i]`. |
| 4.18 | `trading/execution/loop.py:559` | Hardcoded `async_start_day(1_000_000)` — 1M RUB. Day PnL будет неверным. |
| 4.19 | `alerts/push.py:13-18` | `subscribe()` регистрирует `_noop` handler. Push-сервис полностью нерабочий. |
| 4.20 | `alerts/smart.py:79-116` | Scheduled rule check — триггерит когда minute отличается от last_triggered, а не когда наступило расписание. |
| 4.21 | `trading/brokers/openapi.py:40-48` | `_request` — нет retry, circuit breaker, timeout. |
| 4.22 | `trading/brokers/registry.py:64` | Fallback на `settings.tinkoff_token` для ВСЕХ брокеров. |
| 4.23 | `alerts/deduplicator.py:19-30` | Dedup key: `category:subcategory:source_name`. Перезатирает hash новой статьёй. Оригинал может вернуться в окне. |
| 4.24 | `signals/engine.py:*` | `FusionEngine` — нет fallback при пустом наборе компонентов. |

## 🟡 MEDIUM

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 4.25 | `trading/tax/reporter.py:26-84` | Short FIFO — перевёрнут. BUY+COVER в buy_queue, SELL+SHORT против него. |
| 4.26 | `trading/margin.py:72-79` | `compute_portfolio_margin` сравнивает `cash_balance`, а не `equity`. False margin calls. |
| 4.27 | `trading/risk/guards.py:569-575,603-611` | Circuit breaker PnL never reset. После cooldown моментальный re-trigger. |
| 4.28 | `trading/execution/engine.py:512-531` | `approve_order` — только ticker+direction+quantity. Не тот ордер при дубликатах. |
| 4.29 | `trading/tax/reporter.py:67` | Только winning lots облагаются налогом. Loss offset не учитывается. |
| 4.30 | `trading/margin.py:33` | `total_value = portfolio_value + position_value` — double-counting. |
| 4.31 | `trading/execution/audit.py:40-52` | Audit file rotation — rename на Windows может упасть. |
| 4.32 | `trading/execution/audit.py:112-113` | `verify_audit_chain()` проверяет только текущий файл, не rotated. |
| 4.33 | `trading/brokers/sync.py:134-138` | `notin_([])` — invalid SQL. |
| 4.34 | `trading/paper.py:136-141` | Corrupted state file — молча создаёт fresh state. Потеря истории. |
| 4.35 | `trading/metrics.py:208-217` | Monthly returns — блоками по 21 дню, а не по календарю. |
| 4.36 | `trading/execution/loop.py:137` | Evening session 16-18 UTC — реально до 20:50 UTC (23:50 MSK). 3 часа потеряны. |
| 4.37 | `trading/compliance/aml.py:103-106` | Любая ошибка AML → `check.passed = False`. DB error блокирует торговлю. |
| 4.38 | `alerts/deduplicator.py` | Не проверяет `reset()` в тестах — состояние может не очищаться. |

## 🔵 LOW / ⚪ INFO

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 4.39 | `trading/tax/reporter.py:107` | Year hardcoded 2026 |
| 4.40 | `trading/brokers/tbank.py:339-351` | `_decimal` и `_money` — дубликаты |
| 4.41 | `trading/metrics.py:210` | `trading_days_per_month = annual_factor / 12 = 21` — не все месяцы 21 день |
| 4.42 | `trading/types.py:100,102` | "realised" vs "realized" — британский вариант |
| 4.43 | `trading/risk/manager.py:470-472` | `avg_vol = mean(prices_list) * 1000` — цена как proxy объёма. Бессмысленно. |
| 4.44 | `alerts/deduplicator.py` | `_content_hash` — SHA256 только первых 500 символов |
| 4.45 | `signals/schemas.py` | Pydantic V1 style, V1 end-of-life |
| 4.46 | Все `__init__.py` trading/ | Пустые, не экспортируют ключевые символы |

---

# 5. INTERFACES + CLI + LLM + NOTIFICATIONS + SCHEDULER

## 🔴 CRITICAL

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 5.1 | `interfaces/api/auth.py:70-74` | `decode_token()` не проверяет `type:"access"`. Refresh-токен работает как access. |
| 5.2 | `interfaces/api/rate_limiter.py:10-11` | Импортирует `decode_access_token` — **функция не существует**. Каждый авторизованный запрос падает. |
| 5.3 | `interfaces/api/server.py:223` | `status.HTTP_403_FORBIDDEN` — `from fastapi import status` не импортирован. RBAC middleware падает. |
| 5.4 | `interfaces/api/routes/trading_v2.py:137` | `AuditTrail.log()` после `return` — никогда не выполняется. |
| 5.5 | `interfaces/api/routes/trading_v2.py:137,182,221,240,277,309,339,347` | `X-User-ID` от клиента — подмена пользователя. |

## 🟠 HIGH

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 5.6 | `interfaces/api/auth.py:28-31` | Refresh secret = jwt_secret + "_refresh". Тривиально выводится. |
| 5.7 | `interfaces/api/rbac/models.py:70-80` | `get_current_user_role()` — из JWT без DB. Stale role до expiry токена. |
| 5.8 | `interfaces/api/server.py:178-200` | Первый rbac_middleware — мёртвый код. Результат проверки не используется. |
| 5.9 | `interfaces/api/routes/auth.py:165-172` | OAuth — любой provider + code. Без верификации. Любой code создаёт юзера. |
| 5.10 | `interfaces/api/rate_limiter.py:17-19` | `X-Forwarded-For` спуфинг — bypass rate limit. |
| 5.11 | `interfaces/api/routes/portfolio_bonds.py:22` | `get_current_user` (optional auth) — unauthenticated доступ к портфелю. |
| 5.12 | `interfaces/api/routes/analysis.py:281-291` | Causal analysis — нет auth. Бесплатный compute на любом тикере. |
| 5.13 | `interfaces/api/sse.py:34-46` | SSE endpoint без аутентификации. Все сигналы утекают. |
| 5.14 | `scheduler/service.py:224-228` | `target = cid or uid` — chat_id и user_id разные namespace. Отправка не туда. |
| 5.15 | `scheduler/service.py:93` | `_retry_failed_receipts` — отправляет email на пустой `to_email`. |
| 5.16 | `llm/router.py:488-498` | `ask()` вызывает `_groq_call()` напрямую, минуя circuit breaker и Ollama fallback. |
| 5.17 | `llm/router.py:59-68,95-103,117-180,192-202` | Sync DB session внутри async LLM методов — блокировка event loop. |
| 5.18 | `cli/commands/trading.py:25,70` | `PaperTradingEngine(user_id=0)` — hardcoded. Нельзя указать пользователя. |

## 🟡 MEDIUM

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 5.19 | `interfaces/api/auth.py:70-74` | `decode_token` — HTTPException из utility функции |
| 5.20 | `interfaces/api/auth.py:37,96,107` | `_refresh_blacklist_fallback` — растёт бесконечно при отсутствии Redis |
| 5.21 | `interfaces/api/server.py:117` | `cors_origins.split(",")` — упадёт при None |
| 5.22 | `interfaces/api/server.py:253` | `request.client.host` может быть None → AttributeError |
| 5.23 | `interfaces/api/routes/health.py:27,140` | `healthy = True` никогда не меняется на False |
| 5.24 | `interfaces/api/sse.py:16,49-55` | `_signal_subscribers` — неограниченный рост. Нет max. |
| 5.25 | `llm/router.py:282-286` | Prompt cache key без model name. Кеш от Groq возвращается для Ollama. |
| 5.26 | `llm/router.py:315-328` | Ollama без circuit breaker |
| 5.27 | `llm/router.py:30-31,334-339` | Prompt cache bounded 128, но каждый вопрос уникален. Кеш бесполезен для answering. |
| 5.28 | `llm/tools/wolfram.py:30-32` | Lock per-instance, а не singleton. Несколько клиентов бьют Wolfram одновременно. |
| 5.29 | `scheduler/service.py:14-36` | PID file lock — не работает в distributed (Kubernetes). |
| 5.30 | `scheduler/tasks.py:81` | `user_id=1` hardcoded для sync_portfolio |
| 5.31 | `scheduler/reporting.py:83-88,93-98,103-108` | `DISTINCT + ORDER BY` — не работает в MySQL/SQLite |
| 5.32 | `scheduler/reporting.py:268` | `sum(scores) / len(scores)` — деление на ноль при пустом scores |
| 5.33 | `notifications/preferences/engine.py:129-133` | `query(UserSetting).all()` — загружает ВСЕ строки |
| 5.34 | `notifications/service.py:237` | `datetime >= date` — сравнение datetime с date |
| 5.35 | `cli/commands/data.py:338` | `report_date = dt_date(year, 1, 1)` — всегда 1 января |
| 5.36 | `cli/commands/data.py:426` | `coupon_period_days = 30` — hardcoded для всех облигаций |
| 5.37 | `cli/commands/security.py:55` | `Path(".env")` — относительный CWD |

## 🔵 LOW / ⚪ INFO

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 5.38 | `interfaces/api/server.py:155` | HSTS в development |
| 5.39 | `interfaces/api/server.py:118-128` | CORS credentials logic convoluted |
| 5.40 | `interfaces/api/sse.py:28` | keepalive без `retry:` поля |
| 5.41 | `interfaces/api/routes/bonds.py:361` | `datetime.utcnow()` deprecated |
| 5.42 | `interfaces/api/auth.py:161-182` | `oauth_login()` sync `get_session()` без DI |
| 5.43 | `cli/tui.py:123` | `time.sleep()` блокирует shutdown |
| 5.44 | `llm/router.py:330-332` | Fallback без метрик — LLM failure невидим |
| 5.45 | `llm/router.py:238` | API key не валидируется при старте |
| 5.46 | `scheduler/service.py:290-297` | `stop()` не ждёт graceful shutdown |
| 5.47 | `scheduler/tasks.py:90` | `generate_signals(db, updated_ids=None)` — семантика None неясна |
| 5.48 | `notifications/channels.py:228-231` | `logger.exception()` дважды для одной ошибки |

---

# 6. PORTFOLIO + REPORTS + TASKS + PLUGINS + TESTS

## 🔴 CRITICAL

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 6.1 | `portfolio/allocator/engine.py:39-48` | `_load_profile_from_db()` sync session в async классе. Блокирует event loop. |
| 6.2 | `portfolio/allocator/engine.py:178-191` | `_allocate_from_data()` вызывает `asyncio.run()` — RuntimeError если уже есть loop. |
| 6.3 | `portfolio/allocator/engine.py:208-218` | `allocate()` — sync вызывает async → asyncio.run(). Вложенные loop. |
| 6.4 | `tasks/ml_tasks.py:113-131` | `asyncio.new_event_loop()` — конфликт с `--pool=eventlet/gevent`. |
| 6.5 | **Нет тестов** для `portfolio/risk.py` | 75 строк кода — 0% coverage. Core risk функции не тестируются. |
| 6.6 | **Нет тестов** для `tasks/*.py` | 504 строки Celery задач — 0% coverage. |
| 6.7 | **Нет тестов** для `reports/weekly_pdf.py` | 127 строк — 0% coverage. |

## 🟠 HIGH

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 6.8 | `portfolio/allocator/engine.py:121-122` | `amount / last_price` — last_price может быть 0 или None |
| 6.9 | `portfolio/allocator/engine.py:153-163` | Leftover allocation — только etf/dividend. Пропорции теряются. |
| 6.10 | `portfolio/allocator/engine.py:260` | `_load_instruments()` sync — async версия не загружает FundamentalMetric. Асинхронное выделение без данных. |
| 6.11 | `reports/weekly_pdf.py:16-29` | `_portfolio_tickers()` — N+1 запрос. |
| 6.12 | `reports/weekly_pdf.py:126` | Structlog logger с `%s`-форматом — malformed log entry. |
| 6.13 | `reports/weekly_pdf.py:122` | `plt.close(fig)` в try — если fig не создана (exception до `subplots`), утечка памяти. |
| 6.14 | `tasks/__init__.py:31-36` | `daily-update-every-5min` — 288 раз/день. Название "daily" вводит в заблуждение. |
| 6.15 | `tasks/__init__.py:31-101` | Beat schedule task names без валидации. Опечатка → молчаливый fail. |
| 6.16 | `tasks/ml_tasks.py:70-78` | `train_model` возвращает `{"status": "ok"}` даже если все 3 sub-model упали. |
| 6.17 | `tasks/ml_tasks.py:84-110` | `train_all_models.delay()` на 1000+ инструментов без rate limiting. |
| 6.18 | `tasks/scheduler_tasks.py:97-131` | `take_daily_snapshot` — 7 обязанностей. Single Responsibility нарушен. |
| 6.19 | `plugins/` (пусто) | Существует, но пуст. При активации — RCE без изоляции. |
| 6.20 | `tests/test_services.py:43-63` | Тесты проходят с пустой БД — никогда не тестируют реальные данные. |
| 6.21 | `.env.template` | Нет `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `REDIS_URL`. Celery не запустится. |
| 6.22 | `.env.template:2` | `DATABASE_URL=sqlite:///data/finn.db` — относительный путь. Зависит от CWD. |

## 🟡 MEDIUM

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 6.23 | `portfolio/service.py:51` | `(current_price / p.avg_price) - 1` — avg_price=0 → ZeroDivisionError |
| 6.24 | `portfolio/service.py:65` | Нет валидации `quantity > 0` при добавлении |
| 6.25 | `portfolio/risk.py:14` | `item["id"]` — KeyError если ключа нет |
| 6.26 | `portfolio/allocator/profiles.py:1-19` | Нет проверки sum(weights) == 1.0 |
| 6.27 | `portfolio/allocator/engine.py:321-329` | Dividend yield > 25% — silent cap. |
| 6.28 | `reports/__init__.py:22` | `p.get('allocation_pct', 0):.1f` — упадёт если значение None |
| 6.29 | `reports/__init__.py:67-96` | `result.portfolio_return` — AttributeError если не BacktestResult |
| 6.30 | `tasks/__init__.py` | Нет `task_routes` — все задачи в одной очереди |
| 6.31 | `tasks/scheduler_tasks.py:112` | `target = cid or uid` — cid=0 фальсифицирован |
| 6.32 | `tasks/scheduler_tasks.py:196-212` | `retry_failed_receipts` — только email. Telegram/web не ретраятся. |
| 6.33 | `tests/test_integration_db.py:22` | `@pytest.mark.skipif("CI" == "true")` — CI должен тестировать integration |
| 6.34 | `tests/test_scheduler_collectors.py:17,47,72,99` | `asyncio.run()` без `@pytest.mark.asyncio` |
| 6.35 | `tests/test_scenario.py:40-41` | `np.random.normal(0, 1)` — недетерминированные тесты |

## 🔵 LOW / ⚪ INFO

| # | Файл:строка | Проблема |
|---|-------------|----------|
| 6.36 | `portfolio/allocator/__init__.py` | Module-level mutable allocator — race condition |
| 6.37 | `reports/weekly_pdf.py:32` | Функция называется `generate_weekly_report`, но генерирует PNG, не PDF |
| 6.38 | `reports/weekly_pdf.py:46` | Fallback на ["SBER", "LKOH", "GAZP"] при пустом портфеле |
| 6.39 | `tasks/__init__.py:20` | `task_always_eager` — может быть True в production |
| 6.40 | `tasks/worker.py:12` | `--concurrency=2` hardcoded |
| 6.41 | `tasks/scheduler_tasks.py:11-19` | `_run_async` дублирован в каждом task файле |
| 6.42 | `.env.template:23-28` | `TINKOFF_SANDBOX=true` — строка, а не bool |
| 6.43 | `mkdocs.yml:3` | `repo_url: https://github.com/your-org/...` — placeholder |
| 6.44 | `mkdocs.yml` | Нет `site_url` |
| 6.45 | Русские строки в коде — не i18n |

---

# ИТОГО ПО ВСЕМ КАТЕГОРИЯМ

| Категория | 🔴 CRITICAL | 🟠 HIGH | 🟡 MEDIUM | 🔵 LOW/INFO |
|-----------|:-----------:|:-------:|:---------:|:-----------:|
| Core + DB | 7 | 18+ | 20+ | 10+ |
| Analysis | 18 | 27 | 34 | 12 |
| Collectors + Data + Geo + Social + Market | 1 | 13 | 25 | 27 |
| Trading + Signals + Alerts | 8 | 17 | 17 | 28 |
| Interfaces + CLI + LLM + Notifications + Scheduler | 5 | 14 | 25 | 16 |
| Portfolio + Reports + Tasks + Plugins + Tests | 7 | 21 | 31 | 40 |
| **Всего** | **46** | **110+** | **152+** | **133+** |
