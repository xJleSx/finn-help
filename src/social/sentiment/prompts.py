BATCH_ANALYSIS_PROMPT = """Анализируй настроение постов. Ответ — JSON-массив.
Формат: [{{"post_index":N,"ticker":"TICKER","bullish":0-1,"bearish":0-1,"confidence":0-1,"reason":"2-3 слова"}}]

Правила:
- Не про финансы → confidence:0, ticker:null
- Рынок в целом → ticker:null
- Несколько тикеров → отдельный объект на каждый

Посты:
{posts_json}"""

AUTHOR_ANALYSIS_PROMPT = """Оцени автора Пульса. JSON:
{{"reliability":0.0-1.0,"strategy":"long_term|short_term|mixed|unknown","risk":"low|medium|high","notes":"1 фраза"}}

{author_data}"""
