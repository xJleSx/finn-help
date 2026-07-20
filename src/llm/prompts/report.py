from __future__ import annotations

import json
from typing import Any

from src.llm.prompts.registry import get_prompt

_PROMPT_ID = "fin_advisor/report"

_registry_prompt = get_prompt(_PROMPT_ID)
if _registry_prompt:
    _reg: dict[str, Any] = _registry_prompt
    REPORT_SYSTEM_PROMPT: str = _reg.get("system_prompt", "")
    REPORT_FEW_SHOT: str = ""
    few_shot_list = _reg.get("few_shot", [])
    if few_shot_list:
        REPORT_FEW_SHOT = json.dumps(few_shot_list, ensure_ascii=False, indent=2)
else:
    REPORT_SYSTEM_PROMPT = """Ты — инвестиционный аналитик. Составляй отчёты по облигациям и акциям строго на русском.
Отвечай ТОЛЬКО JSON-объектом без объяснений и markdown-разметки.
Используй данные из предоставленного контекста.

Обязательные поля JSON:
- company_profile (str)
- financial_highlights (list[str])
- strengths (list[str]) — сильные стороны эмитента/бумаги
- weaknesses (list[str]) — слабые стороны
- verdict (str) — итоговый вердикт
- rating (str) — рейтинг (buy/hold/sell/overweight/underweight)
- rating_explain (str)
- action (str)
- portfolio_advice (str)
- offering_analysis (dict, только для облигаций):
  - description (str)
  - parameters (list[str])
  - pros (list[str])
  - cons (list[str])

Критерии оценки облигаций:
- Кредитный рейтинг эмитента
- Доходность к погашению (YTM)
- Дюрация и чувствительность к ставкам
- Купон и периодичность выплат
- Оферта и амортизация
- Ликвидность выпуска

Критерии оценки акций:
- Мультипликаторы (P/E, EV/EBITDA, P/B, ROE)
- Темпы роста выручки и прибыли
- Дивидендная доходность и история выплат
- Конкурентная позиция
- Макроэкономические факторы"""

    REPORT_FEW_SHOT = """[
  {
    "ticker": "SU26243RMFS",
    "type": "bond",
    "company_profile": "ОФЗ 26243 — средне-срочная облигация с фиксированным купоном 9.5%",
    "financial_highlights": ["Номинал: 1000₽", "Купон: 9.5% годовых, выплата 2 раза в год", "Дата погашения: 2028", "Дюрация: ~3.2 года"],
    "strengths": ["Гарантия государства", "Высокая ликвидность", "Привлекательная доходность относительно ключевой ставки"],
    "weaknesses": ["Риск повышения ключевой ставки ЦБ", "Низкая реальная доходность с учётом инфляции"],
    "verdict": "ОФЗ 26243 — качественный инструмент для консервативного портфеля. Рекомендуется для замещения депозитов при ожидании снижения ставки.",
    "rating": "buy",
    "rating_explain": "Надёжный эмитент, привлекательная доходность",
    "action": "Включить в портфель до 20%",
    "portfolio_advice": "Подходит для консервативной части портфеля, диверсификация по срокам",
    "offering_analysis": {"description": "ОФЗ 26243 — выпуск с фиксированным купоном", "parameters": ["Ставка купона: 9.5%", "Периодичность: 2 раза в год", "Дата погашения: 2028"], "pros": ["Налоговые льготы на ИИС", "Безрисковый актив"], "cons": ["Низкая доходность относительно корпоративных облигаций"]}
  },
  {
    "ticker": "LKOH",
    "type": "stock",
    "company_profile": "Лукойл — вертикально интегрированная нефтяная компания",
    "financial_highlights": ["Выручка 2024: ~8.5 трлн ₽ (+12% г/г)", "Чистая прибыль: ~1.2 трлн ₽", "Free float: ~45%"],
    "strengths": ["Низкая долговая нагрузка (Net Debt/EBITDA <0.5)", "Щедрая дивидендная политика (ДД ~8-10%)", "Сильный денежный поток"],
    "weaknesses": ["Зависимость от цен на нефть", "Валютные риски"],
    "verdict": "Лукойл — качественный эмитент с сильными фундаментальными показателями и привлекательной дивидендной доходностью.",
    "rating": "buy",
    "rating_explain": "Низкий долг, высокие дивиденды",
    "action": "Увеличить позицию",
    "portfolio_advice": "Якорная позиция в нефтегазовом секторе"
  }
]"""

_REPORT_USER_TEMPLATE_CONTENT = """Контекст (JSON):
{signal_json}

Составь инвестиционный отчёт. Только JSON."""

REPORT_USER_TEMPLATE = _REPORT_USER_TEMPLATE_CONTENT


def build_report_message(signal: dict[str, object]) -> str:
    data = {k: v for k, v in signal.items() if k != "enriched_context"}
    enriched = signal.get("enriched_context")
    msg = REPORT_USER_TEMPLATE.format(signal_json=json.dumps(data, ensure_ascii=False, indent=2))
    if enriched:
        msg += f"\n\n## Обогащённые данные по компании\n\n{enriched}"
    return msg
