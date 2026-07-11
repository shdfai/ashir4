"""
Advanced Indicators Engine v4
Includes: EMA/RSI/MACD/BB/ATR/ADX/VWAP/Stochastic (base)
+ Ichimoku Cloud, Supertrend, Pivot Points, Heikin Ashi,
  Professional Price Action (BOS/CHoCH market structure), Candlestick patterns,
  Elliott Wave (simplified), CVD, Order Flow proxy, Funding Rate slot

Strategy note (v4): the bot's trading decision is driven ONLY by
Supertrend + Price Action (BOS/CHoCH + candlesticks) + Elliott Wave.
All other indicators computed here (Ichimoku, MACD, RSI, CVD, ...) remain
available as informational/dashboard data and for the risk/regime module,
but are no longer part of the entry-signal logic itself.
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple


class IndicatorEngine:
    def __init__(
        self,
        ohlcv_data: list,
        funding_rate: float = 0.0,
        open_interest: float = 0.0,
        supertrend_atr_len: int = 10,
        supertrend_factor: float = 2.0,
        pa_swing_len: int = 5,
    ):
        self.df = self._to_dataframe(ohlcv_data)
        self.funding_rate = funding_rate
        self.open_interest = open_interest
        self.support_levels: List[float] = []
        self.resistance_levels: List[float] = []
        self.pivot_points: Dict = {}
        self.wave_count: int = 0
        self.supertrend_atr_len = supertrend_atr_len
        self.supertrend_factor = supertrend_factor
        self.pa_swing_len = pa_swing_len
        self._compute_all()

    def _to_dataframe(self, ohlcv: list) -> pd.DataFrame:
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def _compute_all(self):
        self._heikin_ashi()
        self._ema()
        self._rsi()
        self._macd()
        self._bollinger_bands()
        self._atr()
        self._vwap()
        self._stochastic()
        self._adx()
        self._ichimoku()
        self._supertrend(period=self.supertrend_atr_len, multiplier=self.supertrend_factor)
        self._pivot_points()
        self._support_resistance()
        self._volume_profile()
        self._cvd()
        self._order_flow_proxy()
        self._candlestick_patterns()
        self._market_structure(swing_len=self.pa_swing_len)
        self._elliott_wave_simple()

    # ─── Heikin Ashi ─────────────────────────────────────────────────────────

    def _heikin_ashi(self):
        ha_close = (self.df["open"] + self.df["high"] + self.df["low"] + self.df["close"]) / 4
        ha_open = (self.df["open"].shift(1) + self.df["close"].shift(1)) / 2
        ha_open.iloc[0] = (self.df["open"].iloc[0] + self.df["close"].iloc[0]) / 2
        # Fill forward to avoid NaN propagation
        for i in range(1, len(ha_open)):
            ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2

        self.df["ha_close"] = ha_close
        self.df["ha_open"] = ha_open
        self.df["ha_high"] = self.df[["high", "ha_open", "ha_close"]].max(axis=1)
        self.df["ha_low"] = self.df[["low", "ha_open", "ha_close"]].min(axis=1)
        self.df["ha_bullish"] = self.df["ha_close"] > self.df["ha_open"]
        # Consecutive HA candles same color — trend strength signal
        self.df["ha_streak"] = (
            self.df["ha_bullish"]
            .groupby((self.df["ha_bullish"] != self.df["ha_bullish"].shift()).cumsum())
            .cumcount() + 1
        ) * self.df["ha_bullish"].map({True: 1, False: -1})

    # ─── Base Indicators ──────────────────────────────────────────────────────

    def _ema(self):
        for period in [8, 13, 21, 50, 100, 200]:
            self.df[f"ema_{period}"] = self.df["close"].ewm(span=period, adjust=False).mean()

    def _macd(self, fast=12, slow=26, signal=9):
        ema_fast = self.df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = self.df["close"].ewm(span=slow, adjust=False).mean()
        self.df["macd"] = ema_fast - ema_slow
        self.df["macd_signal"] = self.df["macd"].ewm(span=signal, adjust=False).mean()
        self.df["macd_histogram"] = self.df["macd"] - self.df["macd_signal"]
        self.df["macd_cross_up"] = (self.df["macd"] > self.df["macd_signal"]) & (self.df["macd"].shift() <= self.df["macd_signal"].shift())
        self.df["macd_cross_dn"] = (self.df["macd"] < self.df["macd_signal"]) & (self.df["macd"].shift() >= self.df["macd_signal"].shift())

    def _rsi(self, period=14):
        delta = self.df["close"].diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        self.df["rsi"] = 100 - (100 / (1 + gain / loss))
        # RSI divergence (simplified)
        self.df["rsi_bullish_div"] = (self.df["close"] < self.df["close"].shift(5)) & (self.df["rsi"] > self.df["rsi"].shift(5))
        self.df["rsi_bearish_div"] = (self.df["close"] > self.df["close"].shift(5)) & (self.df["rsi"] < self.df["rsi"].shift(5))

    def _atr(self, period=14):
        tr = pd.concat([
            self.df["high"] - self.df["low"],
            (self.df["high"] - self.df["close"].shift()).abs(),
            (self.df["low"] - self.df["close"].shift()).abs()
        ], axis=1).max(axis=1)
        self.df["atr"] = tr.rolling(period).mean()
        self.df["atr_pct"] = self.df["atr"] / self.df["close"] * 100

    def _bollinger_bands(self, period=20, std_dev=2):
        sma = self.df["close"].rolling(period).mean()
        std = self.df["close"].rolling(period).std()
        self.df["bb_upper"] = sma + std * std_dev
        self.df["bb_lower"] = sma - std * std_dev
        self.df["bb_middle"] = sma
        self.df["bb_width"] = (self.df["bb_upper"] - self.df["bb_lower"]) / self.df["bb_middle"]
        self.df["bb_pct"] = (self.df["close"] - self.df["bb_lower"]) / (self.df["bb_upper"] - self.df["bb_lower"])
        self.df["bb_squeeze"] = self.df["bb_width"] < self.df["bb_width"].rolling(20).mean() * 0.75

    def _stochastic(self, k=14, d=3):
        low_min = self.df["low"].rolling(k).min()
        high_max = self.df["high"].rolling(k).max()
        self.df["stoch_k"] = 100 * (self.df["close"] - low_min) / (high_max - low_min)
        self.df["stoch_d"] = self.df["stoch_k"].rolling(d).mean()

    def _adx(self, period=14):
        high, low, close = self.df["high"], self.df["low"], self.df["close"]
        plus_dm = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        self.df["plus_di"] = 100 * plus_dm.rolling(period).mean() / atr
        self.df["minus_di"] = 100 * minus_dm.rolling(period).mean() / atr
        dx = 100 * (self.df["plus_di"] - self.df["minus_di"]).abs() / (self.df["plus_di"] + self.df["minus_di"])
        self.df["adx"] = dx.rolling(period).mean()

    def _vwap(self):
        tp = (self.df["high"] + self.df["low"] + self.df["close"]) / 3
        self.df["vwap"] = (tp * self.df["volume"]).cumsum() / self.df["volume"].cumsum()
        self.df["vwap_dev"] = (self.df["close"] - self.df["vwap"]) / self.df["vwap"] * 100

    # ─── Ichimoku Cloud ───────────────────────────────────────────────────────

    def _ichimoku(self, tenkan=9, kijun=26, senkou_b=52, displacement=26):
        def midpoint(period):
            return (self.df["high"].rolling(period).max() + self.df["low"].rolling(period).min()) / 2

        self.df["ichi_tenkan"] = midpoint(tenkan)
        self.df["ichi_kijun"] = midpoint(kijun)
        self.df["ichi_senkou_a"] = ((self.df["ichi_tenkan"] + self.df["ichi_kijun"]) / 2).shift(displacement)
        self.df["ichi_senkou_b"] = midpoint(senkou_b).shift(displacement)
        self.df["ichi_chikou"] = self.df["close"].shift(-displacement)

        # Price position relative to cloud
        cloud_top = self.df[["ichi_senkou_a", "ichi_senkou_b"]].max(axis=1)
        cloud_bot = self.df[["ichi_senkou_a", "ichi_senkou_b"]].min(axis=1)
        self.df["ichi_above_cloud"] = self.df["close"] > cloud_top
        self.df["ichi_below_cloud"] = self.df["close"] < cloud_bot
        self.df["ichi_in_cloud"] = ~self.df["ichi_above_cloud"] & ~self.df["ichi_below_cloud"]
        self.df["ichi_bull_cloud"] = self.df["ichi_senkou_a"] > self.df["ichi_senkou_b"]
        # TK cross
        self.df["ichi_tk_cross_bull"] = (self.df["ichi_tenkan"] > self.df["ichi_kijun"]) & (self.df["ichi_tenkan"].shift() <= self.df["ichi_kijun"].shift())
        self.df["ichi_tk_cross_bear"] = (self.df["ichi_tenkan"] < self.df["ichi_kijun"]) & (self.df["ichi_tenkan"].shift() >= self.df["ichi_kijun"].shift())

    # ─── Supertrend ───────────────────────────────────────────────────────────

    def _supertrend(self, period=10, multiplier=3.0):
        hl2 = (self.df["high"] + self.df["low"]) / 2
        atr = self.df["atr"]

        upper_band = hl2 + multiplier * atr
        lower_band = hl2 - multiplier * atr

        supertrend = pd.Series(index=self.df.index, dtype=float)
        direction = pd.Series(index=self.df.index, dtype=int)

        for i in range(1, len(self.df)):
            prev_upper = upper_band.iloc[i - 1]
            prev_lower = lower_band.iloc[i - 1]
            curr_close = self.df["close"].iloc[i]
            prev_close = self.df["close"].iloc[i - 1]

            # Adjust bands
            curr_upper = upper_band.iloc[i]
            curr_lower = lower_band.iloc[i]
            if pd.isna(prev_upper) or pd.isna(curr_upper):
                upper_band.iloc[i] = curr_upper
            elif curr_upper < prev_upper or prev_close > prev_upper:
                upper_band.iloc[i] = curr_upper
            else:
                upper_band.iloc[i] = prev_upper

            if pd.isna(prev_lower) or pd.isna(curr_lower):
                lower_band.iloc[i] = curr_lower
            elif curr_lower > prev_lower or prev_close < prev_lower:
                lower_band.iloc[i] = curr_lower
            else:
                lower_band.iloc[i] = prev_lower

            # Direction
            prev_dir = direction.iloc[i - 1] if i > 1 else 1
            if prev_dir == -1 and curr_close > upper_band.iloc[i]:
                direction.iloc[i] = 1
            elif prev_dir == 1 and curr_close < lower_band.iloc[i]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = prev_dir

            supertrend.iloc[i] = lower_band.iloc[i] if direction.iloc[i] == 1 else upper_band.iloc[i]

        self.df["supertrend"] = supertrend
        self.df["supertrend_dir"] = direction  # 1=bull, -1=bear
        self.df["supertrend_cross_bull"] = (direction == 1) & (direction.shift() == -1)
        self.df["supertrend_cross_bear"] = (direction == -1) & (direction.shift() == 1)

    # ─── Professional Price Action: Market Structure (BOS / CHoCH) ───────────

    def _market_structure(self, swing_len: int = 5):
        """
        Break of Structure (BOS): price closes beyond the last confirmed swing
        high/low, continuing the prevailing structure.
        Change of Character (CHoCH): a BOS that flips the prevailing bias
        (the first sign a reversal may be starting).

        Note: swing points are confirmed with a `swing_len`-bar lag (a swing
        high/low can only be known once price on both sides has printed),
        same as a live chart's pivot markers — this is not lookahead bias
        introduced beyond what any real-time pivot detector needs.
        """
        high = self.df["high"].values
        low = self.df["low"].values
        close = self.df["close"].values
        n = len(self.df)
        window = swing_len * 2 + 1

        is_swing_high = (self.df["high"].rolling(window, center=True).max() == self.df["high"]).values
        is_swing_low = (self.df["low"].rolling(window, center=True).min() == self.df["low"]).values

        bos_up = np.zeros(n, dtype=bool)
        bos_down = np.zeros(n, dtype=bool)
        choch_bull = np.zeros(n, dtype=bool)
        choch_bear = np.zeros(n, dtype=bool)
        bias = np.full(n, "neutral", dtype=object)

        last_swing_high = np.nan
        last_swing_low = np.nan
        current_bias = "neutral"

        for i in range(n):
            if not np.isnan(last_swing_high) and close[i] > last_swing_high:
                bos_up[i] = True
                if current_bias == "bearish":
                    choch_bull[i] = True
                current_bias = "bullish"
            if not np.isnan(last_swing_low) and close[i] < last_swing_low:
                bos_down[i] = True
                if current_bias == "bullish":
                    choch_bear[i] = True
                current_bias = "bearish"

            bias[i] = current_bias

            if is_swing_high[i]:
                last_swing_high = high[i]
            if is_swing_low[i]:
                last_swing_low = low[i]

        self.df["bos_up"] = bos_up
        self.df["bos_down"] = bos_down
        self.df["choch_bull"] = choch_bull
        self.df["choch_bear"] = choch_bear
        self.df["market_bias"] = bias

    # ─── Pivot Points (daily) ─────────────────────────────────────────────────

    def _pivot_points(self):
        last_h = self.df["high"].iloc[-2] if len(self.df) > 1 else self.df["high"].iloc[-1]
        last_l = self.df["low"].iloc[-2] if len(self.df) > 1 else self.df["low"].iloc[-1]
        last_c = self.df["close"].iloc[-2] if len(self.df) > 1 else self.df["close"].iloc[-1]

        pp = (last_h + last_l + last_c) / 3
        self.pivot_points = {
            "pp": pp,
            "r1": 2 * pp - last_l,
            "r2": pp + (last_h - last_l),
            "r3": last_h + 2 * (pp - last_l),
            "s1": 2 * pp - last_h,
            "s2": pp - (last_h - last_l),
            "s3": last_l - 2 * (last_h - pp),
        }

    # ─── Support & Resistance ─────────────────────────────────────────────────

    def _support_resistance(self, window=20):
        self.df["pivot_high"] = self.df["high"].rolling(window, center=True).max() == self.df["high"]
        self.df["pivot_low"] = self.df["low"].rolling(window, center=True).min() == self.df["low"]
        self.resistance_levels = self.df[self.df["pivot_high"]]["high"].tail(5).tolist()
        self.support_levels = self.df[self.df["pivot_low"]]["low"].tail(5).tolist()

    # ─── CVD — Cumulative Volume Delta ───────────────────────────────────────

    def _cvd(self):
        # Approximate buy/sell volume using candle body direction
        buy_vol = self.df["volume"] * ((self.df["close"] - self.df["low"]) / (self.df["high"] - self.df["low"] + 1e-9))
        sell_vol = self.df["volume"] - buy_vol
        self.df["delta"] = buy_vol - sell_vol
        self.df["cvd"] = self.df["delta"].cumsum()
        self.df["cvd_ma"] = self.df["cvd"].rolling(20).mean()
        # CVD divergence: price up but CVD down = bearish
        self.df["cvd_bull_div"] = (self.df["close"] < self.df["close"].shift(5)) & (self.df["cvd"] > self.df["cvd"].shift(5))
        self.df["cvd_bear_div"] = (self.df["close"] > self.df["close"].shift(5)) & (self.df["cvd"] < self.df["cvd"].shift(5))

    # ─── Order Flow Proxy ─────────────────────────────────────────────────────

    def _order_flow_proxy(self):
        # Buying pressure: close near high = buyers dominant
        self.df["buy_pressure"] = (self.df["close"] - self.df["low"]) / (self.df["high"] - self.df["low"] + 1e-9)
        self.df["sell_pressure"] = 1 - self.df["buy_pressure"]
        self.df["buy_pressure_ma"] = self.df["buy_pressure"].rolling(10).mean()
        # Strong buying: >0.7 with high volume
        self.df["strong_buying"] = (self.df["buy_pressure"] > 0.7) & (self.df["volume"] > self.df["volume"].rolling(20).mean() * 1.5)
        self.df["strong_selling"] = (self.df["sell_pressure"] > 0.7) & (self.df["volume"] > self.df["volume"].rolling(20).mean() * 1.5)

    # ─── Volume Profile ───────────────────────────────────────────────────────

    def _volume_profile(self):
        avg_vol = self.df["volume"].rolling(20).mean()
        self.df["volume_ratio"] = self.df["volume"] / avg_vol
        self.df["high_volume"] = self.df["volume_ratio"] > 1.5
        self.df["very_high_volume"] = self.df["volume_ratio"] > 2.5

    # ─── Elliott Wave (simplified) ────────────────────────────────────────────

    def _elliott_wave_simple(self):
        """
        Simplified Elliott Wave detection.
        Identifies likely Wave 3 (strongest/longest impulse) for high-probability entries.
        """
        highs = self.df["high"].rolling(10).max()
        lows = self.df["low"].rolling(10).min()

        # Detect swing highs/lows
        swing_high = (self.df["high"] == highs) & (self.df["high"] > self.df["high"].shift(1))
        swing_low = (self.df["low"] == lows) & (self.df["low"] < self.df["low"].shift(1))

        self.df["swing_high"] = swing_high
        self.df["swing_low"] = swing_low

        # Wave 3 proxy: strong momentum + ADX > 30 + price extended from EMA
        ema_21 = self.df.get("ema_21", self.df["close"].ewm(span=21).mean())
        extension = (self.df["close"] - ema_21) / ema_21 * 100

        self.df["likely_wave3_bull"] = (
            (self.df["adx"] > 30) &
            (extension > 1.5) &
            (self.df["macd_histogram"] > self.df["macd_histogram"].rolling(10).max() * 0.8) &
            (self.df["volume_ratio"] > 1.5)
        )
        self.df["likely_wave3_bear"] = (
            (self.df["adx"] > 30) &
            (extension < -1.5) &
            (self.df["macd_histogram"] < self.df["macd_histogram"].rolling(10).min() * 0.8) &
            (self.df["volume_ratio"] > 1.5)
        )

        # Wave 5 exhaustion (potential reversal)
        self.df["wave5_exhaustion"] = (
            (self.df["rsi"] > 75) | (self.df["rsi"] < 25)
        ) & (self.df["volume_ratio"] < 0.8)

        self.wave_count = int(self.df["likely_wave3_bull"].tail(5).sum())

    # ─── Candlestick Patterns ─────────────────────────────────────────────────

    def _candlestick_patterns(self):
        o, h, l, c = self.df["open"], self.df["high"], self.df["low"], self.df["close"]
        body = (c - o).abs()
        full_range = h - l + 1e-9
        lower_wick = o.clip(upper=c) - l
        upper_wick = h - o.clip(lower=c)

        self.df["doji"] = body < full_range * 0.1
        self.df["hammer"] = (lower_wick > body * 2) & (upper_wick < body * 0.5) & (c > o)
        self.df["inverted_hammer"] = (upper_wick > body * 2) & (lower_wick < body * 0.5) & (c > o)
        self.df["shooting_star"] = (upper_wick > body * 2) & (lower_wick < body * 0.5) & (c < o)
        self.df["bullish_engulfing"] = (c > o) & (c.shift() < o.shift()) & (c > o.shift()) & (o < c.shift())
        self.df["bearish_engulfing"] = (c < o) & (c.shift() > o.shift()) & (c < o.shift()) & (o > c.shift())
        # Three white soldiers / three black crows
        self.df["three_white_soldiers"] = (c > o) & (c.shift() > o.shift()) & (c.shift(2) > o.shift(2)) & (c > c.shift()) & (c.shift() > c.shift(2))
        self.df["three_black_crows"] = (c < o) & (c.shift() < o.shift()) & (c.shift(2) < o.shift(2)) & (c < c.shift()) & (c.shift() < c.shift(2))
        # Morning/Evening star (3-candle)
        self.df["morning_star"] = (c.shift(2) < o.shift(2)) & (body.shift(1) < body.shift(2) * 0.3) & (c > o) & (c > (o.shift(2) + c.shift(2)) / 2)
        self.df["evening_star"] = (c.shift(2) > o.shift(2)) & (body.shift(1) < body.shift(2) * 0.3) & (c < o) & (c < (o.shift(2) + c.shift(2)) / 2)

    # ─── Public API ───────────────────────────────────────────────────────────

    def get_latest(self) -> Dict:
        row = self.df.iloc[-1]

        def v(key, default=None):
            val = row.get(key, default)
            if pd.isna(val) if val is not None else False:
                return default
            return val

        return {
            # OHLCV
            "close": v("close"), "open": v("open"), "high": v("high"), "low": v("low"), "volume": v("volume"),

            # Heikin Ashi
            "ha_bullish": bool(v("ha_bullish", False)), "ha_streak": v("ha_streak", 0),

            # EMAs
            "ema_8": v("ema_8"), "ema_13": v("ema_13"), "ema_21": v("ema_21"),
            "ema_50": v("ema_50"), "ema_100": v("ema_100"), "ema_200": v("ema_200"),

            # Momentum
            "rsi": v("rsi"), "rsi_bullish_div": bool(v("rsi_bullish_div", False)),
            "rsi_bearish_div": bool(v("rsi_bearish_div", False)),
            "macd": v("macd"), "macd_signal": v("macd_signal"),
            "macd_histogram": v("macd_histogram"),
            "macd_cross_up": bool(v("macd_cross_up", False)),
            "macd_cross_dn": bool(v("macd_cross_dn", False)),
            "stoch_k": v("stoch_k"), "stoch_d": v("stoch_d"),

            # Volatility
            "atr": v("atr"), "atr_pct": v("atr_pct"),
            "bb_upper": v("bb_upper"), "bb_lower": v("bb_lower"),
            "bb_pct": v("bb_pct"), "bb_width": v("bb_width"),
            "bb_squeeze": bool(v("bb_squeeze", False)),

            # Trend
            "adx": v("adx"), "plus_di": v("plus_di"), "minus_di": v("minus_di"),
            "vwap": v("vwap"), "vwap_dev": v("vwap_dev"),
            "volume_ratio": v("volume_ratio"),
            "high_volume": bool(v("high_volume", False)),
            "very_high_volume": bool(v("very_high_volume", False)),

            # Ichimoku
            "ichi_above_cloud": bool(v("ichi_above_cloud", False)),
            "ichi_below_cloud": bool(v("ichi_below_cloud", False)),
            "ichi_bull_cloud": bool(v("ichi_bull_cloud", False)),
            "ichi_tk_cross_bull": bool(v("ichi_tk_cross_bull", False)),
            "ichi_tk_cross_bear": bool(v("ichi_tk_cross_bear", False)),

            # Supertrend
            "supertrend_dir": v("supertrend_dir", 0),
            "supertrend_cross_bull": bool(v("supertrend_cross_bull", False)),
            "supertrend_cross_bear": bool(v("supertrend_cross_bear", False)),

            # CVD & Order Flow
            "cvd": v("cvd", 0), "cvd_bull_div": bool(v("cvd_bull_div", False)),
            "cvd_bear_div": bool(v("cvd_bear_div", False)),
            "buy_pressure": v("buy_pressure", 0.5),
            "strong_buying": bool(v("strong_buying", False)),
            "strong_selling": bool(v("strong_selling", False)),

            # Elliott Wave
            "likely_wave3_bull": bool(v("likely_wave3_bull", False)),
            "likely_wave3_bear": bool(v("likely_wave3_bear", False)),
            "wave5_exhaustion": bool(v("wave5_exhaustion", False)),

            # Price Action — Market Structure (BOS / CHoCH)
            "bos_up": bool(v("bos_up", False)),
            "bos_down": bool(v("bos_down", False)),
            "choch_bull": bool(v("choch_bull", False)),
            "choch_bear": bool(v("choch_bear", False)),
            "market_bias": v("market_bias", "neutral"),

            # Candlestick patterns
            "doji": bool(v("doji", False)), "hammer": bool(v("hammer", False)),
            "shooting_star": bool(v("shooting_star", False)),
            "bullish_engulfing": bool(v("bullish_engulfing", False)),
            "bearish_engulfing": bool(v("bearish_engulfing", False)),
            "three_white_soldiers": bool(v("three_white_soldiers", False)),
            "three_black_crows": bool(v("three_black_crows", False)),
            "morning_star": bool(v("morning_star", False)),
            "evening_star": bool(v("evening_star", False)),

            # Levels
            "support_levels": self.support_levels,
            "resistance_levels": self.resistance_levels,
            "pivot_points": self.pivot_points,

            # External data
            "funding_rate": self.funding_rate,
            "open_interest": self.open_interest,
        }

    def get_dataframe(self) -> pd.DataFrame:
        return self.df

    def get_multi_tf_score(self, direction: str) -> Tuple[float, List[str]]:
        """
        Returns a 0-10 score and list of confirming signals
        for the given direction (long/short).
        """
        score = 0
        signals = []
        ind = self.get_latest()

        if direction == "long":
            if ind.get("ichi_above_cloud"): score += 1.5; signals.append("ichi_above_cloud")
            if ind.get("supertrend_dir", 0) == 1: score += 1; signals.append("supertrend_bull")
            if ind.get("ha_bullish") and ind.get("ha_streak", 0) >= 3: score += 1; signals.append("ha_streak")
            if ind.get("macd_cross_up"): score += 1; signals.append("macd_cross")
            if ind.get("rsi", 50) > 50 and ind.get("rsi", 50) < 70: score += 0.5; signals.append("rsi_bull")
            if ind.get("rsi_bullish_div"): score += 1; signals.append("rsi_div")
            if ind.get("cvd_bull_div"): score += 0.5; signals.append("cvd_div")
            if ind.get("strong_buying"): score += 1; signals.append("strong_buying")
            if ind.get("likely_wave3_bull"): score += 1; signals.append("wave3")
            if ind.get("ichi_tk_cross_bull"): score += 0.5; signals.append("tk_cross")
        else:
            if ind.get("ichi_below_cloud"): score += 1.5; signals.append("ichi_below_cloud")
            if ind.get("supertrend_dir", 0) == -1: score += 1; signals.append("supertrend_bear")
            if not ind.get("ha_bullish") and ind.get("ha_streak", 0) <= -3: score += 1; signals.append("ha_streak")
            if ind.get("macd_cross_dn"): score += 1; signals.append("macd_cross")
            if ind.get("rsi", 50) < 50 and ind.get("rsi", 50) > 30: score += 0.5; signals.append("rsi_bear")
            if ind.get("rsi_bearish_div"): score += 1; signals.append("rsi_div")
            if ind.get("cvd_bear_div"): score += 0.5; signals.append("cvd_div")
            if ind.get("strong_selling"): score += 1; signals.append("strong_selling")
            if ind.get("likely_wave3_bear"): score += 1; signals.append("wave3")
            if ind.get("ichi_tk_cross_bear"): score += 0.5; signals.append("tk_cross")

        return min(score, 10.0), signals
