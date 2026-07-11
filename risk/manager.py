"""
Dynamic Risk Management
AI-driven position sizing, ATR-based SL/TP, dynamic leverage, and
daily-loss circuit breaker. Works identically for paper and live modes.
"""
from typing import Dict, Tuple
from loguru import logger
from config.settings import settings


class RiskManager:
    def __init__(self):
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.open_positions_count = 0
        self.trade_history = []
        self._trading_halted = False
        self._halt_reason = ""

    # ─── Position Sizing ─────────────────────────────────────────────────────

    def calculate_position_size(
        self, balance: float, entry_price: float, stop_loss_price: float,
        risk_multiplier: float = 1.0, confidence: float = 0.7,
    ) -> Dict:
        base_risk = settings.RISK_PER_TRADE
        adjusted_risk = base_risk * risk_multiplier * self._confidence_factor(confidence)
        adjusted_risk = min(adjusted_risk, base_risk * 2)  # hard cap

        dollar_risk = balance * (adjusted_risk / 100)

        stop_distance = abs(entry_price - stop_loss_price)
        stop_distance_pct = stop_distance / entry_price if entry_price else 0.01
        if stop_distance_pct == 0:
            stop_distance_pct = 0.01

        position_size_usdt = dollar_risk / stop_distance_pct
        max_position_usdt = balance * settings.DEFAULT_LEVERAGE
        position_size_usdt = min(position_size_usdt, max_position_usdt * 0.5)

        quantity = position_size_usdt / entry_price if entry_price else 0

        return {
            "quantity": round(quantity, 6),
            "position_value_usdt": round(position_size_usdt, 2),
            "risk_usdt": round(dollar_risk, 2),
            "risk_pct": round(adjusted_risk, 2),
        }

    def _confidence_factor(self, confidence: float) -> float:
        if confidence >= 0.85:
            return 1.3
        elif confidence >= 0.75:
            return 1.0
        elif confidence >= 0.60:
            return 0.7
        return 0.4

    # ─── SL / TP ─────────────────────────────────────────────────────────────

    def calculate_sl_tp(
        self, entry_price: float, direction: str, atr: float,
        atr_multiplier_sl: float = 1.5, risk_reward_ratio: float = 2.5,
        regime: str = "ranging",
    ) -> Dict:
        if regime == "trending":
            risk_reward_ratio = 3.0
        elif regime == "volatile":
            risk_reward_ratio = 2.0
            atr_multiplier_sl = 2.0

        sl_distance = atr * atr_multiplier_sl
        tp_distance = sl_distance * risk_reward_ratio

        if direction == "long":
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - tp_distance

        return {
            "stop_loss": round(stop_loss, 6),
            "take_profit": round(take_profit, 6),
            "risk_reward": risk_reward_ratio,
        }

    # ─── Dynamic Leverage ────────────────────────────────────────────────────

    def get_dynamic_leverage(self, confidence: float, regime: str, atr_pct: float) -> int:
        base = settings.DEFAULT_LEVERAGE

        if regime == "volatile" or atr_pct > 3.0:
            leverage = max(settings.MIN_LEVERAGE, base // 3)
        elif regime == "trending" and confidence > 0.80:
            leverage = min(settings.MAX_LEVERAGE, int(base * 1.5))
        elif confidence < 0.60:
            leverage = max(settings.MIN_LEVERAGE, base // 2)
        else:
            leverage = base

        return max(settings.MIN_LEVERAGE, min(leverage, settings.MAX_LEVERAGE))

    # ─── Circuit Breakers ────────────────────────────────────────────────────

    def check_can_trade(self, balance: float) -> Tuple[bool, str]:
        if self._trading_halted:
            return False, f"Trading halted: {self._halt_reason}"

        if balance < settings.MIN_BALANCE_USDT:
            return False, f"Balance too low: ${balance:.2f} < ${settings.MIN_BALANCE_USDT}"

        if self.open_positions_count >= settings.MAX_OPEN_TRADES:
            return False, f"Max positions reached: {self.open_positions_count}/{settings.MAX_OPEN_TRADES}"

        if balance > 0:
            daily_loss_pct = (self.daily_pnl / balance) * 100
            if daily_loss_pct <= -settings.MAX_DAILY_LOSS:
                self._halt_trading(f"Daily loss limit hit: {daily_loss_pct:.2f}%")
                return False, self._halt_reason

        return True, "OK"

    def _halt_trading(self, reason: str):
        self._trading_halted = True
        self._halt_reason = reason
        logger.warning(f"🛑 Trading HALTED: {reason}")

    def resume_trading(self):
        self._trading_halted = False
        self._halt_reason = ""
        self.daily_pnl = 0.0
        self.daily_trades = 0
        logger.info("✅ Trading resumed, daily stats reset")

    # ─── Tracking ────────────────────────────────────────────────────────────

    def record_trade(self, pnl: float, symbol: str, direction: str):
        self.daily_pnl += pnl
        self.daily_trades += 1
        self.trade_history.append({"pnl": pnl, "symbol": symbol, "direction": direction})

        status = "✅ WIN" if pnl > 0 else "❌ LOSS"
        logger.info(f"{status} | {symbol} {direction} | PnL: ${pnl:.2f} | Daily: ${self.daily_pnl:.2f}")

    def update_open_positions(self, count: int):
        self.open_positions_count = count

    def get_stats(self) -> Dict:
        wins = [t for t in self.trade_history if t["pnl"] > 0]
        win_rate = len(wins) / len(self.trade_history) if self.trade_history else 0
        return {
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_trades": self.daily_trades,
            "open_positions": self.open_positions_count,
            "win_rate": round(win_rate * 100, 1),
            "trading_halted": self._trading_halted,
            "halt_reason": self._halt_reason,
        }
