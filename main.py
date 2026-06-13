#!/usr/bin/env python3
"""FinAdvisor — AI финансовый ассистент для MOEX.

Usage:
  uv run finn init        # Инициализация БД
  uv run finn update SBER # Загрузка данных
  uv run finn analyze SBER # Анализ с LLM-советом
  uv run finn list        # Список инструментов
  uv run finn rates       # Курсы валют

  uv run api              # FastAPI (http://127.0.0.1:8000)
  cd web && npm run dev   # Next.js (http://127.0.0.1:3000)
"""

if __name__ == "__main__":
    from src.cli import app
    app()
