---
description: Run trading ML scripts — signal classification, risk management, portfolio analytics, feature engineering, regime detection, and more
---

Trading ML scripts are in `.opencode/skills-tools/trading-ml/`. Each subfolder contains a SKILL.md (read for usage) and Python scripts:

| Skill | Scripts | Purpose |
|-------|---------|---------|
| `signal-classification` | `train_classifier.py`, `walk_forward_backtest.py` | XGBoost/LightGBM signal models |
| `feature-engineering` | `build_features.py`, `feature_importance.py` | OHLCV feature computation |
| `risk-management` | `drawdown_analyzer.py`, `risk_dashboard.py` | Drawdown and risk monitoring |
| `portfolio-analytics` | `analyze_portfolio.py`, `compare_strategies.py` | Portfolio metrics |
| `regime-detection` | `detect_regime.py`, `regime_backtest.py` | Market regime identification |
| `volatility-modeling` | `estimate_volatility.py`, `vol_forecast.py` | Volatility estimation |
| `walk-forward-validation` | `walk_forward.py`, `overfit_detector.py` | Time-series validation |
| `sentiment-analysis` | `keyword_sentiment.py`, `sentiment_scanner.py` | News sentiment |
| `correlation-analysis` | `correlation_matrix.py`, `rolling_correlation.py` | Asset correlation |
| `position-sizing` | `size_calculator.py`, `portfolio_sizer.py` | Kelly/position sizing |
| `pandas-ta` | `compute_indicators.py`, `multi_indicator_scan.py` | Technical indicators |
| `fixed-income` | `bond_calculator.py` | Bond pricing (MOEX OFZ) |

Usage:
1. Read the relevant SKILL.md for methodology and parameters
2. Run the script with `python SCRIPT.py --help` first to see arguments
3. Execute with appropriate parameters

User request: $ARGUMENTS
