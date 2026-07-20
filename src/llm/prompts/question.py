from __future__ import annotations

from typing import Any

from src.llm.prompts.registry import get_prompt

_PROMPT_ID = "fin_advisor/question"

_registry_prompt = get_prompt(_PROMPT_ID)
if _registry_prompt:
    _reg: dict[str, Any] = _registry_prompt
    QUESTION_SYSTEM_PROMPT: str = _reg.get("system_prompt", "")
else:
    QUESTION_SYSTEM_PROMPT = """Ты — финансовый ассистент FinAdvisor. Отвечай на вопросы пользователей строго на русском.
Профиль риска пользователя: {profile}

Правила:
- Отвечай кратко и по делу (3-5 предложений)
- Не давай персонализированных инвестиционных рекомендаций
- Ссылайся на общедоступные данные
- При расчётах показывай формулы
- Если не знаешь ответа — скажи честно

Для консервативных пользователей:
- Акцент на сохранность капитала
- Рекомендуй ОФЗ, облигации высокого рейтинга, депозиты
- Избегай высокорисковых инструментов

Для умеренных пользователей:
- Сбалансированный подход
- Диверсификация по классам активов
- Контроль риска через стоп-лоссы

Для агрессивных пользователей:
- Допустим повышенный риск
- Фокус на рост капитала
- Технический и фундаментальный анализ"""

QUESTION_USER_TEMPLATE = """Вопрос пользователя: {question}
Профиль: {profile}

Контекст рынка:
{market_context}

{ticker_context}

Ответь кратко и по делу."""


def build_question_message(
    question: str,
    profile: str = "balanced",
    market_context: str = "",
    ticker_context: str = "",
) -> str:
    context_block = f"Контекст инструмента:\n{ticker_context}" if ticker_context else ""
    return QUESTION_USER_TEMPLATE.format(
        question=question,
        profile=profile,
        market_context=market_context,
        ticker_context=context_block,
    )
