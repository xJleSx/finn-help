import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class AdvancedTechnicalAnalyzer:

    def ichimoku(
        self,
        df: pd.DataFrame,
        tenkan_period: int = 9,
        kijun_period: int = 26,
        senkou_b_period: int = 52,
        displacement: int = 26,
    ) -> pd.DataFrame:
        if df.empty:
            return df
        df = df.copy()

        high = df["high"]
        low = df["low"]
        close = df["close"]

        tenkan_sen = (high.rolling(tenkan_period).max() + low.rolling(tenkan_period).min()) / 2
        kijun_sen = (high.rolling(kijun_period).max() + low.rolling(kijun_period).min()) / 2
        senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(displacement)
        senkou_span_b = ((high.rolling(senkou_b_period).max() + low.rolling(senkou_b_period).min()) / 2).shift(displacement)
        chikou_span = close.shift(-displacement)

        df["tenkan_sen"] = tenkan_sen
        df["kijun_sen"] = kijun_sen
        df["senkou_span_a"] = senkou_span_a
        df["senkou_span_b"] = senkou_span_b
        df["chikou_span"] = chikou_span

        df["ichimoku_cloud_top"] = np.where(
            senkou_span_a >= senkou_span_b, senkou_span_a, senkou_span_b
        )
        df["ichimoku_cloud_bottom"] = np.where(
            senkou_span_a >= senkou_span_b, senkou_span_b, senkou_span_a
        )
        df["ichimoku_cloud_color"] = np.where(
            senkou_span_a >= senkou_span_b, "green", "red"
        )
        df["ichimoku_above_cloud"] = close > df["ichimoku_cloud_top"]
        df["ichimoku_below_cloud"] = close < df["ichimoku_cloud_bottom"]

        tk_cross = pd.Series(index=df.index, dtype=object)
        tk_bullish = (tenkan_sen > kijun_sen) & (tenkan_sen.shift(1) <= kijun_sen.shift(1))
        tk_bearish = (tenkan_sen < kijun_sen) & (tenkan_sen.shift(1) >= kijun_sen.shift(1))
        tk_cross[tk_bullish] = "bullish"
        tk_cross[tk_bearish] = "bearish"
        df["ichimoku_tk_cross"] = tk_cross

        kk_cross = pd.Series(index=df.index, dtype=object)
        kk_bullish = (senkou_span_a > senkou_span_b) & (senkou_span_a.shift(1) <= senkou_span_b.shift(1))
        kk_bearish = (senkou_span_a < senkou_span_b) & (senkou_span_a.shift(1) >= senkou_span_b.shift(1))
        kk_cross[kk_bullish] = "bullish"
        kk_cross[kk_bearish] = "bearish"
        df["ichimoku_kk_cross"] = kk_cross

        return df

    def fibonacci_retracement(
        self, df: pd.DataFrame, trend: str = "up"
    ) -> pd.DataFrame:
        if df.empty or len(df) < 2:
            return df
        df = df.copy()

        n = len(df)
        lookback = min(n, 100)
        recent = df.iloc[-lookback:]

        if trend == "up":
            swing_low_idx = recent["low"].idxmin()
            swing_high_idx = recent["high"].idxmax()
            if swing_high_idx < swing_low_idx:
                swing_low_idx = recent.loc[:swing_high_idx, "low"].idxmin()
        else:
            swing_high_idx = recent["high"].idxmax()
            swing_low_idx = recent["low"].idxmin()
            if swing_low_idx < swing_high_idx:
                swing_high_idx = recent.loc[:swing_low_idx, "high"].idxmax()

        swing_low = df.loc[swing_low_idx, "low"]
        swing_high = df.loc[swing_high_idx, "high"]
        diff = swing_high - swing_low

        ratios = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618]
        level_cols = {}
        for r in ratios:
            level = swing_high - diff * r if trend == "up" else swing_low + diff * r
            col = f"fib_{int(r * 1000):04d}"
            df[col] = level
            level_cols[col] = level

        close = df["close"].iloc[-1]
        current_level = None
        for r in sorted(ratios, reverse=(trend == "down")):
            level = swing_high - diff * r if trend == "up" else swing_low + diff * r
            col = f"fib_{int(r * 1000):04d}"
            if current_level is None:
                if (trend == "up" and close <= level) or (trend == "down" and close >= level):
                    current_level = col
            elif current_level is not None:
                pass

        fib_ratios_sorted = sorted(ratios, reverse=(trend == "down"))
        for i, r in enumerate(fib_ratios_sorted):
            col = f"fib_{int(r * 1000):04d}"
            level = swing_high - diff * r if trend == "up" else swing_low + diff * r
            if i == 0:
                if (trend == "up" and close >= level) or (trend == "down" and close <= level):
                    df["fib_current_level"] = col
                    break
            else:
                prev_r = fib_ratios_sorted[i - 1]
                prev_level = swing_high - diff * prev_r if trend == "up" else swing_low + diff * prev_r
                if (trend == "up" and prev_level >= close >= level) or (
                    trend == "down" and prev_level <= close <= level
                ):
                    df["fib_current_level"] = col
                    break
        else:
            df["fib_current_level"] = fib_ratios_sorted[-1]

        df["fib_swing_low"] = swing_low
        df["fib_swing_high"] = swing_high

        return df

    def volume_profile(self, df: pd.DataFrame, bins: int = 24) -> pd.DataFrame:
        if df.empty or len(df) < 2:
            return df
        df = df.copy()

        price_min = df["low"].min()
        price_max = df["high"].max()

        if price_max == price_min:
            price_max = price_min + 0.01

        bin_edges = np.linspace(price_min, price_max, bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

        volume_at_price = np.zeros(bins)
        for i in range(len(df)):
            row = df.iloc[i]
            for b in range(bins):
                if row["high"] >= bin_edges[b] and row["low"] <= bin_edges[b + 1]:
                    range_frac = (
                        min(row["high"], bin_edges[b + 1])
                        - max(row["low"], bin_edges[b])
                    ) / max(row["high"] - row["low"], 1e-10)
                    volume_at_price[b] += row["volume"] * range_frac

        poc_idx = np.argmax(volume_at_price)
        poc_price = bin_centers[poc_idx]
        total_volume = volume_at_price.sum()

        sorted_indices = np.argsort(volume_at_price)[::-1]
        cum_vol = 0.0
        va_indices = []
        for idx in sorted_indices:
            cum_vol += volume_at_price[idx]
            va_indices.append(idx)
            if total_volume > 0 and cum_vol / total_volume >= 0.7:
                break

        va_high = max(bin_centers[va_indices])
        va_low = min(bin_centers[va_indices])

        df["volume_profile_poc"] = poc_price
        df["volume_profile_va_high"] = va_high
        df["volume_profile_va_low"] = va_low
        df["volume_profile_poc_support"] = df["close"] <= poc_price * 1.02
        df["volume_profile_poc_resistance"] = df["close"] >= poc_price * 0.98

        return df

    def money_flow_index(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        if df.empty:
            return df
        df = df.copy()

        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        raw_money_flow = typical_price * df["volume"]

        positive_flow = raw_money_flow.where(typical_price > typical_price.shift(1), 0.0)
        negative_flow = raw_money_flow.where(typical_price < typical_price.shift(1), 0.0)

        pos_sum = positive_flow.rolling(period).sum()
        neg_sum = negative_flow.rolling(period).sum()

        money_ratio = pos_sum / neg_sum.replace(0, np.nan)
        df["mfi"] = 100 - (100 / (1 + money_ratio))
        df["mfi"] = np.where(
            neg_sum == 0,
            np.where(pos_sum == 0, 50.0, 100.0),
            df["mfi"],
        )

        return df

    def stochastic_oscillator(
        self, df: pd.DataFrame, k_period: int = 14, d_period: int = 3
    ) -> pd.DataFrame:
        if df.empty:
            return df
        df = df.copy()

        lowest_low = df["low"].rolling(k_period).min()
        highest_high = df["high"].rolling(k_period).max()

        range_val = highest_high - lowest_low
        df["stoch_k"] = np.where(
            range_val != 0,
            (df["close"] - lowest_low) / range_val * 100,
            50.0,
        )
        df["stoch_d"] = df["stoch_k"].rolling(d_period).mean()

        return df

    def obv(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        df = df.copy()

        close = df["close"]
        volume = df["volume"]

        obv_values = np.zeros(len(df))
        obv_values[0] = volume.iloc[0]

        for i in range(1, len(df)):
            if close.iloc[i] > close.iloc[i - 1]:
                obv_values[i] = obv_values[i - 1] + volume.iloc[i]
            elif close.iloc[i] < close.iloc[i - 1]:
                obv_values[i] = obv_values[i - 1] - volume.iloc[i]
            else:
                obv_values[i] = obv_values[i - 1]

        df["obv"] = obv_values
        return df

    def williams_r(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        if df.empty:
            return df
        df = df.copy()

        highest_high = df["high"].rolling(period).max()
        lowest_low = df["low"].rolling(period).min()

        range_val = highest_high - lowest_low
        df["williams_r"] = np.where(
            range_val != 0,
            -((highest_high - df["close"]) / range_val) * 100,
            -50.0,
        )

        return df

    def parabolic_sar(
        self,
        df: pd.DataFrame,
        acceleration: float = 0.02,
        max_acceleration: float = 0.2,
    ) -> pd.DataFrame:
        if df.empty or len(df) < 2:
            return df
        df = df.copy()

        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        length = len(df)
        sar = np.zeros(length)
        af = np.zeros(length)
        trend = np.zeros(length, dtype=bool)

        sar[0] = low[0]
        af[0] = acceleration
        trend[0] = True

        if close[1] >= close[0]:
            trend[1] = True
            ep = high[0]
            sar[1] = sar[0] + af[0] * (ep - sar[0])
        else:
            trend[1] = False
            ep = low[0]
            sar[1] = sar[0] + af[0] * (ep - sar[0])

        if trend[1]:
            sar[1] = min(sar[1], low[0])
        else:
            sar[1] = max(sar[1], high[0])

        ep = high[0] if trend[1] else low[0]

        for i in range(2, length):
            prev_trend = trend[i - 1]

            if prev_trend:
                sar[i] = sar[i - 1] + af[i - 1] * (ep - sar[i - 1])
                sar[i] = min(
                    sar[i],
                    min(low[i - 1], low[i - 2]) if i >= 2 else low[i - 1],
                )
            else:
                sar[i] = sar[i - 1] + af[i - 1] * (ep - sar[i - 1])
                sar[i] = max(
                    sar[i],
                    max(high[i - 1], high[i - 2]) if i >= 2 else high[i - 1],
                )

            if prev_trend and sar[i] > low[i]:
                trend[i] = False
                sar[i] = ep
                af[i] = acceleration
                ep = low[i]
            elif not prev_trend and sar[i] < high[i]:
                trend[i] = True
                sar[i] = ep
                af[i] = acceleration
                ep = high[i]
            else:
                trend[i] = prev_trend
                if prev_trend and high[i] > ep:
                    ep = high[i]
                    af[i] = min(af[i - 1] + acceleration, max_acceleration)
                elif not prev_trend and low[i] < ep:
                    ep = low[i]
                    af[i] = min(af[i - 1] + acceleration, max_acceleration)
                else:
                    af[i] = af[i - 1]

        df["parabolic_sar"] = sar
        return df

    def compute_all_advanced(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        df = df.sort_values("date").copy()

        df = self.ichimoku(df)
        df = self.fibonacci_retracement(df)
        df = self.volume_profile(df)
        df = self.money_flow_index(df)
        df = self.stochastic_oscillator(df)
        df = self.obv(df)
        df = self.williams_r(df)
        df = self.parabolic_sar(df)

        return df
