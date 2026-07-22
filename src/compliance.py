DISCLAIMER = (
    "⚠️ Не является инвестиционной рекомендацией. "
    "Все решения о покупке/продаже активов вы принимаете самостоятельно. "
    "Прошлая доходность не гарантирует будущих результатов."
)


def with_disclaimer(text: str) -> str:
    if DISCLAIMER in text:
        return text
    return f"{text}\n\n{DISCLAIMER}"


async def attach_disclaimer_to_telegram(text: str) -> str:
    return with_disclaimer(text)


async def attach_disclaimer_to_email(text: str) -> str:
    return with_disclaimer(text)
