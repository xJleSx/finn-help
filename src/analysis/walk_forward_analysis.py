from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from src.trading.metrics import PerformanceMetrics, compute_metrics

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardConfig:
    n_splits: int = 5
    gap: int = 20
    min_train_size: int = 252
    purge: bool = True
    test_size: int = 63
    annual_factor: int = 252


@dataclass
class WalkForwardFold:
    fold: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    train_metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    test_metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    n_trades: int = 0


@dataclass
class WalkForwardResult:
    config: WalkForwardConfig = field(default_factory=WalkForwardConfig)
    folds: list[WalkForwardFold] = field(default_factory=list)
    ticker: str = ""
    start_date: str = ""
    end_date: str = ""

    @property
    def avg_test_return(self) -> float:
        if not self.folds:
            return 0.0
        return float(np.mean([f.test_metrics.total_return for f in self.folds]))

    @property
    def avg_test_sharpe(self) -> float:
        if not self.folds:
            return 0.0
        return float(np.mean([f.test_metrics.sharpe for f in self.folds]))

    @property
    def avg_test_max_dd(self) -> float:
        if not self.folds:
            return 0.0
        return float(np.mean([f.test_metrics.max_drawdown for f in self.folds]))

    @property
    def stability(self) -> float:
        """Lower is better — std of test returns across folds."""
        if len(self.folds) < 2:
            return 0.0
        returns = [f.test_metrics.total_return for f in self.folds]
        return float(np.std(returns))

    @property
    def oos_sharpe(self) -> float:
        """Weighted out-of-sample Sharpe (all test periods concatenated)."""
        all_test_returns: list[float] = []
        for f in self.folds:
            all_test_returns.extend(f.test_metrics.equity_curve)
        if len(all_test_returns) < 5:
            return 0.0
        return compute_metrics(all_test_returns).sharpe

    def summary(self) -> str:
        lines = [
            "📊 *Walk-Forward Analysis*",
            f"   Ticker: {self.ticker}",
            f"   Period: {self.start_date} — {self.end_date}",
            f"   Folds: {len(self.folds)}",
            f"   Config: {self.config.n_splits} splits, gap={self.config.gap}",
            "",
            f"📈 Avg Test Return: {self.avg_test_return:+.2%}",
            f"⚙ Avg Test Sharpe: {self.avg_test_sharpe:.2f}",
            f"⚠ Avg Test Max DD: {self.avg_test_max_dd:.2%}",
            f"📊 Stability (std): {self.stability:.2%}",
            f"🔬 OOS Sharpe: {self.oos_sharpe:.2f}",
            "",
        ]
        for f in self.folds:
            lines.append(
                f"  Fold {f.fold}: train={f.train_metrics.sharpe:.2f} / {f.train_metrics.total_return:+.1%} "
                f"→ test={f.test_metrics.sharpe:.2f} / {f.test_metrics.total_return:+.1%} "
                f"(DD={f.test_metrics.max_drawdown:.1%})"
            )
        return "\n".join(lines)


def run_walk_forward(
    prices: list[float],
    config: WalkForwardConfig | None = None,
    ticker: str = "",
    start_date: str = "",
    end_date: str = "",
) -> WalkForwardResult:
    if config is None:
        config = WalkForwardConfig()
    result = WalkForwardResult(config=config, ticker=ticker, start_date=start_date, end_date=end_date)

    n = len(prices)
    if n < config.min_train_size + config.test_size + config.gap + 10:
        logger.warning("Not enough data for walk-forward: %d rows", n)
        return result

    fold_size = (n - config.min_train_size) // config.n_splits
    if fold_size < config.test_size:
        fold_size = config.test_size

    for i in range(config.n_splits):
        test_end = n - i * fold_size
        test_start = max(test_end - fold_size, config.min_train_size + config.gap)
        train_end = test_start - config.gap

        if train_end < config.min_train_size or test_start >= test_end:
            continue

        train_prices = prices[:train_end]
        test_prices = prices[test_start:test_end]

        if len(train_prices) < config.min_train_size or len(test_prices) < config.test_size:
            continue

        train_equity = [p / train_prices[0] for p in train_prices]
        test_equity = [p / test_prices[0] for p in test_prices]

        fold = WalkForwardFold(
            fold=i + 1,
            train_start=0,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            train_metrics=compute_metrics(train_equity, annual_factor=config.annual_factor),
            test_metrics=compute_metrics(test_equity, annual_factor=config.annual_factor),
        )
        result.folds.append(fold)

    return result


def run_combinatorial_purged_cv(
    prices: list[float],
    n_splits: int = 6,
    n_test_splits: int = 2,
    gap: int = 20,
    min_train_size: int = 252,
    annual_factor: int = 252,
) -> WalkForwardResult:
    """Combinatorial Purged Cross-Validation (CPCV) as described by Marcos López de Prado.
    Generates all combinations of train/test splits, purging overlapping periods.
    """
    config = WalkForwardConfig(n_splits=n_splits, gap=gap, min_train_size=min_train_size, annual_factor=annual_factor)
    result = WalkForwardResult(config=config)

    n = len(prices)
    if n < min_train_size + 10:
        return result

    from itertools import combinations

    split_points = np.linspace(0, n, n_splits + 1, dtype=int)[1:-1]

    if len(split_points) < n_test_splits:
        return result

    test_combos = list(combinations(range(len(split_points) + 1), n_test_splits))

    fold_id = 0
    for test_idxes in test_combos:
        test_start = split_points[test_idxes[0]] if test_idxes[0] < len(split_points) else 0
        test_end = split_points[test_idxes[-1] + 1] if test_idxes[-1] + 1 < len(split_points) else n

        if test_start < gap:
            test_start = gap
        if test_start >= test_end:
            continue

        train_end = test_start - gap
        if train_end < min_train_size:
            continue

        train_prices = prices[:train_end]
        test_prices = prices[test_start:test_end]

        if len(train_prices) < min_train_size or len(test_prices) < 5:
            continue

        train_equity = [p / train_prices[0] for p in train_prices]
        test_equity = [p / test_prices[0] for p in test_prices]

        fold_id += 1
        fold = WalkForwardFold(
            fold=fold_id,
            train_start=0,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            train_metrics=compute_metrics(train_equity, annual_factor=annual_factor),
            test_metrics=compute_metrics(test_equity, annual_factor=annual_factor),
        )
        result.folds.append(fold)

    return result
