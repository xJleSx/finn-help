import csv
import logging
from typing import Any
from io import StringIO

logger = logging.getLogger(__name__)


def generate_portfolio_csv(positions: list[dict[str, Any]]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Тикер", "Название", "Кол-во", "Средняя", "Цена", "Стоимость", "Доля", "Прибыль %"])
    for p in positions:
        writer.writerow(
            [
                p.get("ticker", ""),
                p.get("name", ""),
                p.get("quantity", 0),
                p.get("avg_price", 0),
                p.get("current_price", 0),
                p.get("value", 0),
                f"{p.get('allocation_pct', 0):.1f}%" if "allocation_pct" in p else "",
                f"{p.get('profit_pct', 0):.1f}%",
            ]
        )
    return output.getvalue()


def generate_signals_csv(signals: list[dict[str, Any]]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Тикер", "Действие", "Уверенность", "Score", "Причины"])
    for s in signals:
        writer.writerow(
            [
                s.get("ticker", ""),
                s.get("action", ""),
                s.get("confidence", 0),
                s.get("weighted_score", 0),
                "; ".join(s.get("reasons", [])),
            ]
        )
    return output.getvalue()


def generate_analysis_csv(ticker: str, signal: dict[str, Any], prices: list[dict[str, Any]]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([f"Анализ: {ticker}"])
    writer.writerow([])
    writer.writerow(["Параметр", "Значение"])
    writer.writerow(["Действие", signal.get("action", "N/A")])
    writer.writerow(["Уверенность", signal.get("confidence", 0)])
    writer.writerow(["Score", signal.get("weighted_score", 0)])
    writer.writerow(["Макс. доля", f"{signal.get('max_portfolio_pct', 0)}%"])
    writer.writerow([])
    writer.writerow(["Причины"])
    for r in signal.get("reasons", []):
        writer.writerow(["", r])
    writer.writerow([])
    writer.writerow(["Дата", "Цена закрытия"])
    for p in prices[-30:]:
        writer.writerow([p.get("date", ""), p.get("close", 0)])
    return output.getvalue()


def generate_backtest_csv(result: Any) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Параметр", "Значение"])
    writer.writerow(["Доходность", f"{result.portfolio_return:.2%}"])
    writer.writerow(["Benchmark", f"{result.benchmark_return:.2%}"])
    writer.writerow(["Альфа", f"{result.alpha:.2%}"])
    writer.writerow(["Sharpe", f"{result.portfolio_sharpe:.2f}"])
    writer.writerow(["Sortino", f"{result.portfolio_sortino:.2f}"])
    writer.writerow(["Max DD", f"{result.portfolio_max_dd:.2%}"])
    writer.writerow(["Win Rate", f"{result.win_rate:.1%}"])
    writer.writerow(["Прибыль фактор", f"{result.profit_factor:.2f}"])
    writer.writerow(["Трейдов", result.trades])
    writer.writerow(["Комиссии", f"{result.total_commission:.0f}"])
    writer.writerow(["Проскальзывание", f"{result.total_slippage:.0f}"])
    if result.monte_carlo:
        writer.writerow([])
        writer.writerow(["Monte-Carlo", f"{result.monte_carlo.simulations} симуляций"])
        writer.writerow(["Средняя", f"{result.monte_carlo.mean_return:.2%}"])
        writer.writerow(["VaR 95%", f"{result.monte_carlo.var_95:.2%}"])
        writer.writerow(["CVaR 95%", f"{result.monte_carlo.cvar_95:.2%}"])
    if result.regime:
        writer.writerow(["Режим", result.regime.regime])
    writer.writerow([])
    writer.writerow(["Период", "Портфель", "Benchmark"])
    for i in range(len(result.dates)):
        pr = result.portfolio_returns[i] if i < len(result.portfolio_returns) else 0
        br = result.benchmark_returns[i] if i < len(result.benchmark_returns) else 0
        writer.writerow([result.dates[i], f"{pr:.4f}", f"{br:.4f}"])
    return output.getvalue()


def generate_sector_report_csv(sector_perf: dict[str, float], sector_vol: dict[str, float]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Сектор", "Доходность 30д", "Волатильность (годовая)"])
    all_sectors = sorted(set(list(sector_perf.keys()) + list(sector_vol.keys())))
    for s in all_sectors:
        perf = sector_perf.get(s, "")
        vol = sector_vol.get(s, "")
        writer.writerow(
            [
                s,
                f"{perf:.1%}" if isinstance(perf, float) else perf,
                f"{vol:.1%}" if isinstance(vol, float) else vol,
            ]
        )
    return output.getvalue()
