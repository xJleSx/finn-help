from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

MODEL_PRICING: dict[str, dict[str, float]] = {
    "llama-3.3-70b-versatile": {"input_per_1k": 0.00059, "output_per_1k": 0.00079, "provider": "groq"},
    "llama-3.1-8b-instant": {"input_per_1k": 0.00004, "output_per_1k": 0.00004, "provider": "groq"},
    "qwen2.5:7b": {"input_per_1k": 0.0, "output_per_1k": 0.0, "provider": "ollama"},
    "default": {"input_per_1k": 0.001, "output_per_1k": 0.002, "provider": "unknown"},
}


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
    input_cost = (input_tokens / 1000) * pricing["input_per_1k"]
    output_cost = (output_tokens / 1000) * pricing["output_per_1k"]
    return round(input_cost + output_cost, 6)


@dataclass
class UsageRecord:
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CostTracker:
    def __init__(self) -> None:
        self._records: list[UsageRecord] = []
        self._budget_limit: Optional[float] = None

    def set_budget(self, daily_limit: float) -> None:
        self._budget_limit = daily_limit

    def record(
        self,
        model: str,
        provider: str,
        input_text: str,
        output_text: str,
    ) -> UsageRecord:
        input_tokens = estimate_tokens(input_text)
        output_tokens = estimate_tokens(output_text)
        cost = compute_cost(model, input_tokens, output_tokens)
        rec = UsageRecord(
            model=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
        )
        self._records.append(rec)
        logger.debug("LLM cost: %s/%s: %.6f", provider, model, cost)
        return rec

    @property
    def total_cost(self) -> float:
        return round(sum(r.cost for r in self._records), 4)

    @property
    def total_tokens(self) -> int:
        return sum(r.input_tokens + r.output_tokens for r in self._records)

    def daily_cost(self) -> float:
        today = datetime.now(timezone.utc).date()
        return round(
            sum(r.cost for r in self._records if r.timestamp.date() == today),
            4,
        )

    def budget_exceeded(self) -> bool:
        if self._budget_limit is None:
            return False
        return self.daily_cost() >= self._budget_limit

    def summary(self) -> str:
        if not self._records:
            return "No LLM usage recorded."
        lines = [
            f"Total cost: ${self.total_cost:.4f}",
            f"Total tokens: {self.total_tokens}",
            f"Daily cost: ${self.daily_cost():.4f}",
            f"Requests: {len(self._records)}",
        ]
        if self._budget_limit is not None:
            lines.append(f"Daily budget: ${self._budget_limit:.2f} ({'exceeded' if self.budget_exceeded() else 'ok'})")
        return "\n".join(lines)


_cost_tracker: CostTracker = CostTracker()


def get_cost_tracker() -> CostTracker:
    return _cost_tracker
