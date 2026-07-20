from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.social.topics import (
    TOPIC_KEYWORDS,
    classify_topic,
    extract_key_entities,
    extract_topics_batch,
    topic_summary,
)


def test_classify_topic_finance():
    assert classify_topic("акции сбербанка выросли") == "finance"


def test_classify_topic_oil():
    assert classify_topic("нефть brent подорожала") == "oil_gas"


def test_classify_topic_macro():
    assert classify_topic("ключевая ставка цб изменилась") == "macro"


def test_classify_topic_other():
    assert classify_topic("погода сегодня хорошая") == "other"


def test_classify_topic_empty():
    assert classify_topic("") == "other"


def test_extract_entities():
    entities = extract_key_entities("SBER вырос, MOEX упал")
    assert "SBER" in entities
    assert "MOEX" in entities


def test_topic_summary():
    posts = [
        {"text": "акции растут"},
        {"text": "нефть падает"},
        {"text": "погода хорошая"},
    ]
    summary = topic_summary(posts)
    assert "finance" in summary
    assert "oil_gas" in summary
    assert "other" in summary


def test_extract_topics_batch():
    results = extract_topics_batch(["SBER вырос на 5%", "погода сегодня"])
    assert len(results) == 2
    assert results[0]["topic"] == "finance"
    assert results[1]["topic"] == "other"


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=0, max_size=200))
@settings(max_examples=100)
def test_classify_topic_hypothesis(text):
    topic = classify_topic(text)
    valid_topics = set(TOPIC_KEYWORDS.keys()) | {"other"}
    assert topic in valid_topics
