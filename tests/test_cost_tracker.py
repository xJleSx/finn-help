from __future__ import annotations

from src.llm.cost_tracker import CostTracker, compute_cost, estimate_tokens, get_cost_tracker


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello") == 1
    assert estimate_tokens("a" * 100) == 25


def test_compute_cost():
    cost = compute_cost("llama-3.3-70b-versatile", 1000, 500)
    assert cost > 0


def test_compute_cost_unknown_model():
    cost = compute_cost("unknown-model", 1000, 500)
    assert cost > 0


def test_cost_tracker_record():
    ct = CostTracker()
    ct.record("llama-3.3-70b-versatile", "groq", "a" * 4000, "b" * 2000)
    assert ct.total_cost > 0
    assert ct.total_tokens > 0


def test_cost_tracker_summary():
    ct = CostTracker()
    summary = ct.summary()
    assert "No LLM usage" in summary
    ct.record("test", "groq", "hello", "world")
    summary = ct.summary()
    assert "Total cost" in summary


def test_cost_tracker_budget():
    ct = CostTracker()
    ct.set_budget(0.001)
    assert not ct.budget_exceeded()
    ct.record("llama-3.3-70b-versatile", "groq", "a" * 4000, "b" * 2000)
    assert ct.daily_cost() > 0


def test_cost_tracker_singleton():
    ct1 = get_cost_tracker()
    ct2 = get_cost_tracker()
    assert ct1 is ct2
