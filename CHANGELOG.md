# Changelog

## 0.1.0 (2026-07-11)

### Added
- Initial release of FinAdvisor — AI-powered financial advisor for MOEX markets
- Technical, fundamental, ML, sentiment, geopolitical, and multi-timeframe analysis
- Signal fusion engine with user-profile-weighted scoring
- Portfolio management with risk profiling and rebalancing
- Multi-broker trading (T-Bank, Alor, BCS, Finam) with dry-run and auto modes
- Telegram bot with interactive commands and alerts
- Web dashboard (Next.js) with real-time charts
- Backtesting and paper trading engines
- AML and compliance checks
- Alert system with smart rules and push notifications
- ML models: XGBoost, LightGBM, CatBoost, Prophet/StatsModels
- LLM integration via Groq and Ollama
- Comprehensive signal fusion
- Sentiment analysis from news and social media
- Geopolitical risk scoring
- Feature drift detection and model retraining
- Rate limiting, circuit breakers, and resilience patterns
- Prometheus metrics and Sentry error tracking
- PostgreSQL with PgBouncer connection pooling
- Redis caching with in-memory fallback
- Docker multi-stage builds and docker-compose setup
- Nginx reverse proxy with security headers and rate limiting
- CI pipeline with linting, type checking, and testing
- Alembic database migrations
- CLI interface via Typer
