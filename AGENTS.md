# Phase 0 — Cleanup
- [x] Delete src/brokers/tinkoff.py
- [x] Delete src/collectors/kase.py
- [x] Update README

# Phase 1 — Wire to scheduler
- [x] Wire src/analysis/summarizer.py -> daily_update()
- [x] Wire src/data/sector_impact_engine.py -> daily_update()
- [x] Wire src/analysis/rebalancing.py -> weekly_update()
- [x] Wire src/collectors/social.py -> daily_update()
- [x] Wire src/analysis/risk_explorer.py -> API endpoints
- [x] Wire src/interfaces/telegram_alerter.py -> broadcast pipeline

# Phase 2 — Social sentiment
- [x] Connect collectors/social.py with social/sentiment/
- [x] Wire social/features.py into collect_social_sentiment()
- [x] Wire ml/sentiment_evolution.py into collect_social_sentiment()

# Phase 3 — Causal & advanced
- [x] Wire inference/causal.py -> API endpoints
- [x] Wire risk_explorer.py portfolio/ticker endpoints

# Phase 4 — Tests & docs
- [x] Integration tests for wired modules (summarizer, rebalancing, risk_explorer, alert_generators)
- [x] Update README with full architecture map

# Phase 5 — Refactoring
- [x] #7 Report formatting duplication (fundamental.py + response_formatter.py)
- [x] #10 Handler boilerplate decorator в telegram.py
- [x] #3 Groq/Ollama client duplication в router.py
- [x] #2 Triple _allocate_from_data в allocator.py
