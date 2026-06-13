# FinAdvisor — AI Financial Advisor

## Project structure
- `src/` — Python backend (CLI + API)
- `web/` — Next.js dashboard
- `data/` — SQLite database

## Commands
- `uv run finn init` — init database
- `uv run finn update SBER` — fetch data for ticker
- `uv run finn analyze SBER` — full analysis (use --no-llm to skip LLM)
- `uv run finn list` — list instruments
- `uv run finn rates` — CBR exchange rates
- `uv run api` — start FastAPI (uvicorn src.interfaces.api.server:app)
- `uv run web` — start Next.js (cd web && npm run dev)

## Architecture
- MOEX ISS + CBR + RSS → Collector
- TA-Lib/pandas → Technical Analyzer
- Prophet/XGBoost → ML Predictor (future)
- Sentiment Divergence + GeoRisk Scorer → Geo module
- Groq → ollama → Fallback → LLM Router
- FastAPI → Next.js → Web Dashboard

## Environment
- `.env` — API keys (Groq, Tinkoff)
- Python 3.13+
- Node.js 22+
