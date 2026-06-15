import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class TechnicalAnalyzer:
    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        df = df.sort_values("date").copy()

        df = self.sma(df, 20)
        df = self.sma(df, 50)
        df = self.sma(df, 200)
        df = self.rsi(df, 14)
        df = self.macd(df)
        df = self.bollinger_bands(df, 20)
        df = self.volume_sma(df, 20)
        df = self.atr(df, 14)

        return df

    def sma(self, df: pd.DataFrame, period: int) -> pd.DataFrame:
        col = f"sma_{period}"
        df[col] = df["close"].rolling(window=period).mean()
        return df

    def rsi(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        avg_gain = gain.ewm(span=period, adjust=False).mean()
        avg_loss = loss.ewm(span=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))
        df["rsi"] = df["rsi"].fillna(50.0)
        return df

    def macd(self, df: pd.DataFrame) -> pd.DataFrame:
        ema_12 = df["close"].ewm(span=12, adjust=False).mean()
        ema_26 = df["close"].ewm(span=26, adjust=False).mean()
        df["macd_line"] = ema_12 - ema_26
        df["macd_signal"] = df["macd_line"].ewm(span=9, adjust=False).mean()
        df["macd_hist"] = df["macd_line"] - df["macd_signal"]
        return df

    def bollinger_bands(self, df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        df["bb_mid"] = df["close"].rolling(window=period).mean()
        std = df["close"].rolling(window=period).std()
        df["bb_upper"] = df["bb_mid"] + (std * 2)
        df["bb_lower"] = df["bb_mid"] - (std * 2)
        return df

    def volume_sma(self, df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        df["volume_sma_20"] = df["volume"].rolling(window=period).mean()
        return df

    def atr(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=period).mean()
        return df

    def generate_signal(self, df: pd.DataFrame) -> dict:
        if df.empty or len(df) < 50:
            return {"action": "NEUTRAL", "confidence": 0.0, "reasons": ["недостаточно данных"]}

        latest = df.iloc[-1]
        reasons = []
        score = 0.0
        max_score = 0.0

        if not pd.isna(latest.get("rsi")):
            max_score += 1.0
            if latest["rsi"] < 30:
                score += 1.0
                reasons.append(f"RSI={latest['rsi']:.1f} — перепроданность")
            elif latest["rsi"] > 70:
                score -= 1.0
                reasons.append(f"RSI={latest['rsi']:.1f} — перекупленность")
            else:
                reasons.append(f"RSI={latest['rsi']:.1f} — нейтрально")

        if not pd.isna(latest.get("macd_hist")):
            max_score += 1.0
            prev = df.iloc[-2] if len(df) > 1 else latest
            if latest["macd_hist"] > 0 and prev.get("macd_hist", 0) <= 0:
                score += 1.0
                reasons.append("MACD гистограмма перешла в положительную зону — сигнал к покупке")
            elif latest["macd_hist"] < 0 and prev.get("macd_hist", 0) >= 0:
                score -= 1.0
                reasons.append("MACD гистограмма перешла в отрицательную зону — сигнал к продаже")
            else:
                reasons.append(f"MACD гистограмма={latest['macd_hist']:.2f}")

        sma_cols = ["sma_20", "sma_50"]
        for col in sma_cols:
            if not pd.isna(latest.get(col)):
                max_score += 0.5
                price_col = "close"
                price = latest.get(price_col, 0)
                if price > latest[col]:
                    score += 0.5
                    reasons.append(f"Цена выше {col.upper()}={latest[col]:.2f}")
                else:
                    score -= 0.5
                    reasons.append(f"Цена ниже {col.upper()}={latest[col]:.2f}")

        if not pd.isna(latest.get("bb_lower")) and not pd.isna(latest.get("bb_upper")):
            max_score += 0.5
            if latest["close"] <= latest["bb_lower"]:
                score += 0.5
                reasons.append("Цена у нижней границы Bollinger Bands — возможен отскок")
            elif latest["close"] >= latest["bb_upper"]:
                score -= 0.5
                reasons.append("Цена у верхней границы Bollinger Bands — возможна коррекция")

        normalized = score / max_score if max_score > 0 else 0.0

        if normalized > 0.3:
            action = "BUY"
        elif normalized < -0.3:
            action = "SELL"
        else:
            action = "HOLD"

        return {
            "action": action,
            "confidence": abs(normalized),
            "score": normalized,
            "reasons": reasons,
        }
