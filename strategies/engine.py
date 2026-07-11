"""
Strategy Engine v4 — Pure Technical Strategy (No Machine Learning)
===================================================================
The entire trading decision is made by ONE unified, fully-explainable
rule-based strategy combining three layers, mirroring the project's
Pine Script indicator:

    1) SuperTrend      → trend direction / entry trigger (a flip)
    2) Price Action    → confirmation via BOS/CHoCH market structure
                          and/or a recognized candlestick pattern
    3) Elliott Wave     → a simplified, informational exhaustion filter
                          (skips entries in a likely Wave-5 exhaustion zone)

There is no AI/ML ensemble, no scalping/swing sub-strategy voting, and no
black-box confidence prediction. Every confidence number is a transparent
sum of the rule weights below, so any signal can be explained line by line.
"""
from typing import Dict, List, Optional, Tuple

from core.indicators import IndicatorEngine


class StrategyResult:
    def __init__(self, action: str, direction: str, confidence: float, reason: str, indicators: Dict):
        self.action = action
        self.direction = direction
        self.confidence = confidence
        self.reason = reason
        self.indicators = indicators

    def __repr__(self):
        return f"<{self.action} {self.direction} {self.confidence:.0%} — {self.reason}>"


def assess_market_regime(ind: Dict) -> Dict:
    """
    Pure rule-based volatility/trend regime classifier (no ML).
    Used only for position sizing / leverage adjustment — it does not
    influence whether a signal fires.
    """
    adx = ind.get("adx") or 20
    atr_pct = ind.get("atr_pct") or 1.0
    bb_width = ind.get("bb_width") or 0.02
    funding = ind.get("funding_rate") or 0

    if adx > 35 and atr_pct < 2.5:
        regime, risk_mult = "strong_trend", 1.3
    elif adx > 25 and atr_pct < 2.0:
        regime, risk_mult = "trending", 1.1
    elif bb_width > 0.06 or atr_pct > 4.0:
        regime, risk_mult = "volatile", 0.4
    elif bb_width < 0.02:
        regime, risk_mult = "squeeze", 0.6
    else:
        regime, risk_mult = "ranging", 0.8

    if abs(funding) > 0.001:
        risk_mult *= 0.7

    return {
        "regime": regime, "risk_multiplier": risk_mult,
        "adx": adx, "atr_pct": atr_pct, "bb_width": bb_width, "funding_rate": funding,
    }


class SuperTrendPriceActionElliottStrategy:
    """
    The single trading strategy used everywhere (live bot + backtester).

    Entry rules
    -----------
    LONG:  SuperTrend just flipped bullish
           AND (a bullish candlestick pattern OR a bullish BOS) confirms it
           AND we are not inside a likely Wave-5 exhaustion zone

    SHORT: SuperTrend just flipped bearish
           AND (a bearish candlestick pattern OR a bearish BOS) confirms it
           AND we are not inside a likely Wave-5 exhaustion zone

    Confidence (fully transparent, capped at 0.95)
    -----------------------------------------------
        base                       0.60   (SuperTrend flip)
      + candlestick confirmation  +0.12
      + BOS in trade direction    +0.08
      + CHoCH (fresh reversal)    +0.05
      + likely Wave-3 (best RR)   +0.15
    """
    name = "SuperTrend+PriceAction+ElliottWave"

    def analyze(self, ind: Dict) -> Optional[Tuple[str, float, str]]:
        st_bull_flip = ind.get("supertrend_cross_bull", False)
        st_bear_flip = ind.get("supertrend_cross_bear", False)

        if st_bull_flip:
            return self._evaluate_long(ind)
        if st_bear_flip:
            return self._evaluate_short(ind)
        return None

    def _evaluate_long(self, ind: Dict) -> Optional[Tuple[str, float, str]]:
        candlestick_confirm = bool(
            ind.get("bullish_engulfing") or ind.get("hammer") or
            ind.get("morning_star") or ind.get("three_white_soldiers")
        )
        pa_confirm = candlestick_confirm or ind.get("bos_up")
        if not pa_confirm:
            return None
        if ind.get("wave5_exhaustion"):
            return None

        confidence = 0.60
        reasons = ["supertrend_flip_bull"]
        if candlestick_confirm:
            confidence += 0.12
            reasons.append("candlestick_confirm")
        if ind.get("bos_up"):
            confidence += 0.08
            reasons.append("bos_up")
        if ind.get("choch_bull"):
            confidence += 0.05
            reasons.append("choch_bull")
        if ind.get("likely_wave3_bull"):
            confidence += 0.15
            reasons.append("wave3_bull")

        return "long", round(min(confidence, 0.95), 3), "+".join(reasons)

    def _evaluate_short(self, ind: Dict) -> Optional[Tuple[str, float, str]]:
        candlestick_confirm = bool(
            ind.get("bearish_engulfing") or ind.get("shooting_star") or
            ind.get("evening_star") or ind.get("three_black_crows")
        )
        pa_confirm = candlestick_confirm or ind.get("bos_down")
        if not pa_confirm:
            return None
        if ind.get("wave5_exhaustion"):
            return None

        confidence = 0.60
        reasons = ["supertrend_flip_bear"]
        if candlestick_confirm:
            confidence += 0.12
            reasons.append("candlestick_confirm")
        if ind.get("bos_down"):
            confidence += 0.08
            reasons.append("bos_down")
        if ind.get("choch_bear"):
            confidence += 0.05
            reasons.append("choch_bear")
        if ind.get("likely_wave3_bear"):
            confidence += 0.15
            reasons.append("wave3_bear")

        return "short", round(min(confidence, 0.95), 3), "+".join(reasons)


class StrategyEngine:
    """
    Public entry point used by both the live bot (core/bot.py) and the
    backtester (backtesting/engine.py). Wraps the single unified strategy
    above plus the rule-based market-regime assessor.
    """

    def __init__(self):
        self.strategy = SuperTrendPriceActionElliottStrategy()

    async def analyze(
        self,
        ohlcv_map: Dict[str, List],
        symbol: str,
        funding_rate: float = 0.0,
        open_interest: float = 0.0,
        min_confidence: float = 0.55,
    ) -> StrategyResult:
        primary_tf = "15m"
        ohlcv = ohlcv_map.get(primary_tf)
        if not ohlcv or len(ohlcv) < 50:
            return StrategyResult("HOLD", "none", 0.0, "insufficient_data", {})

        eng = IndicatorEngine(ohlcv, funding_rate, open_interest)
        ind = eng.get_latest()
        regime = assess_market_regime(ind)

        result = self.strategy.analyze(ind)
        if not result:
            return StrategyResult(
                "HOLD", "none", 0.0,
                f"no_signal regime={regime['regime']}",
                {**ind, "regime": regime},
            )

        direction, confidence, reason = result
        if confidence < min_confidence:
            return StrategyResult(
                "HOLD", "none", 0.0,
                f"low_confidence({confidence:.0%}) regime={regime['regime']}",
                {**ind, "regime": regime},
            )

        return StrategyResult(
            action="ENTER", direction=direction, confidence=confidence,
            reason=f"{reason} regime={regime['regime']}",
            indicators={**ind, "regime": regime},
        )

    def analyze_indicators(self, ind: Dict) -> Optional[Tuple[str, float, str]]:
        """
        Synchronous variant for callers (e.g. the backtester) that already
        have a computed indicator dict and don't need the async I/O path.
        """
        return self.strategy.analyze(ind)

    def check_exit(self, position: Dict, ind: Dict) -> Tuple[bool, str]:
        direction = position.get("direction", "long")
        rsi = ind.get("rsi") or 50

        if direction == "long":
            if rsi > 83:
                return True, "rsi_overbought"
            if ind.get("bearish_engulfing") or ind.get("three_black_crows"):
                return True, "reversal_pattern"
            if ind.get("supertrend_dir", 1) == -1:
                return True, "supertrend_flip"
            if ind.get("choch_bear"):
                return True, "choch_bear"
            if ind.get("wave5_exhaustion") and rsi > 70:
                return True, "wave5_exhaustion"
        else:
            if rsi < 17:
                return True, "rsi_oversold"
            if ind.get("bullish_engulfing") or ind.get("three_white_soldiers"):
                return True, "reversal_pattern"
            if ind.get("supertrend_dir", -1) == 1:
                return True, "supertrend_flip"
            if ind.get("choch_bull"):
                return True, "choch_bull"
            if ind.get("wave5_exhaustion") and rsi < 30:
                return True, "wave5_exhaustion"

        return False, ""
