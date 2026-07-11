"""
Advanced Position Manager v3
Handles: Trailing Stop Loss, Partial Take Profit, Break Even,
Time-based Exit, Drawdown-based leverage reduction.
"""
import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from loguru import logger

from config.settings import settings


class ManagedPosition:
    """Tracks one open position with all management state"""

    def __init__(
        self, symbol: str, direction: str, entry_price: float,
        quantity: float, leverage: int,
        stop_loss: float, take_profit: float,
        trade_db_id: Optional[int] = None,
    ):
        self.symbol = symbol
        self.direction = direction       # long | short
        self.entry_price = entry_price
        self.quantity = quantity
        self.leverage = leverage
        self.initial_sl = stop_loss
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.initial_tp = take_profit
        self.trade_db_id = trade_db_id

        self.opened_at = datetime.utcnow()
        self.peak_price = entry_price    # for trailing SL
        self.partial_tp_done = False     # first TP already taken
        self.break_even_done = False
        self.remaining_quantity = quantity


class PositionManager:
    """
    Manages all open positions with advanced exit logic:
    - Trailing Stop Loss: follows price, locks in profit
    - Partial Take Profit: closes 50% at TP1, lets rest run
    - Break Even: moves SL to entry when 1:1 R:R reached
    - Time-based exit: close if position hasn't moved in X minutes
    - Drawdown protection: auto-reduce leverage when equity drops
    """

    def __init__(self):
        self.positions: Dict[str, ManagedPosition] = {}

    def register(self, position: ManagedPosition):
        self.positions[position.symbol] = position
        logger.info(f"📋 Position registered: {position.symbol} {position.direction}")

    def unregister(self, symbol: str):
        self.positions.pop(symbol, None)

    def get(self, symbol: str) -> Optional[ManagedPosition]:
        return self.positions.get(symbol)

    def all_positions(self) -> List[ManagedPosition]:
        return list(self.positions.values())

    # ─── Per-candle Management Logic ─────────────────────────────────────────

    async def check_position(
        self, pos: ManagedPosition, current_price: float
    ) -> List[Dict]:
        """
        Check one position against all management rules.
        Returns list of actions: [{'action': 'close_partial'|'close_full'|'update_sl', ...}]
        """
        actions = []
        now = datetime.utcnow()

        # ── 1. Time-based exit ───────────────────────────────────────────────
        age_minutes = (now - pos.opened_at).total_seconds() / 60
        pnl_pct = self._pnl_pct(pos, current_price)

        if age_minutes > settings.TIME_BASED_EXIT_MINUTES and pnl_pct < 0:
            actions.append({
                "action": "close_full",
                "symbol": pos.symbol,
                "reason": f"time_based_exit ({age_minutes:.0f}min, pnl={pnl_pct:.2f}%)",
            })
            return actions

        # ── 2. Trailing Stop Loss ────────────────────────────────────────────
        if settings.TRAILING_STOP_ENABLED:
            action = self._check_trailing_sl(pos, current_price)
            if action:
                actions.append(action)
                if action["action"] == "close_full":
                    return actions

        # ── 3. Break Even ────────────────────────────────────────────────────
        if settings.BREAK_EVEN_ENABLED and not pos.break_even_done:
            be_action = self._check_break_even(pos, current_price)
            if be_action:
                actions.append(be_action)

        # ── 4. Partial Take Profit ───────────────────────────────────────────
        if settings.PARTIAL_TP_ENABLED and not pos.partial_tp_done:
            pt_action = self._check_partial_tp(pos, current_price)
            if pt_action:
                actions.append(pt_action)

        # ── 5. Full TP hit ───────────────────────────────────────────────────
        if self._tp_hit(pos, current_price):
            actions.append({
                "action": "close_full",
                "symbol": pos.symbol,
                "reason": "tp_hit",
            })
            return actions

        # ── 6. SL hit ────────────────────────────────────────────────────────
        if self._sl_hit(pos, current_price):
            actions.append({
                "action": "close_full",
                "symbol": pos.symbol,
                "reason": "sl_hit",
            })

        return actions

    # ─── Trailing Stop Loss ───────────────────────────────────────────────────

    def _check_trailing_sl(self, pos: ManagedPosition, price: float) -> Optional[Dict]:
        trail_pct = settings.TRAILING_STOP_PCT / 100

        if pos.direction == "long":
            if price > pos.peak_price:
                pos.peak_price = price
                new_sl = pos.peak_price * (1 - trail_pct)
                if new_sl > pos.stop_loss:
                    pos.stop_loss = new_sl
                    return {"action": "update_sl", "symbol": pos.symbol, "new_sl": new_sl, "reason": "trailing_sl"}
            if price <= pos.stop_loss and pos.stop_loss > pos.initial_sl:
                return {"action": "close_full", "symbol": pos.symbol, "reason": "trailing_sl_hit"}
        else:
            if price < pos.peak_price:
                pos.peak_price = price
                new_sl = pos.peak_price * (1 + trail_pct)
                if new_sl < pos.stop_loss:
                    pos.stop_loss = new_sl
                    return {"action": "update_sl", "symbol": pos.symbol, "new_sl": new_sl, "reason": "trailing_sl"}
            if price >= pos.stop_loss and pos.stop_loss < pos.initial_sl:
                return {"action": "close_full", "symbol": pos.symbol, "reason": "trailing_sl_hit"}

        return None

    # ─── Break Even ───────────────────────────────────────────────────────────

    def _check_break_even(self, pos: ManagedPosition, price: float) -> Optional[Dict]:
        entry = pos.entry_price
        tp = pos.take_profit
        trigger_rr = settings.BREAK_EVEN_TRIGGER_RR

        if pos.direction == "long":
            reward = abs(tp - entry)
            if price >= entry + reward * trigger_rr:
                pos.stop_loss = entry + 0.0001  # just above entry to cover fee
                pos.break_even_done = True
                return {"action": "update_sl", "symbol": pos.symbol, "new_sl": pos.stop_loss, "reason": "break_even"}
        else:
            reward = abs(entry - tp)
            if price <= entry - reward * trigger_rr:
                pos.stop_loss = entry - 0.0001
                pos.break_even_done = True
                return {"action": "update_sl", "symbol": pos.symbol, "new_sl": pos.stop_loss, "reason": "break_even"}

        return None

    # ─── Partial Take Profit ──────────────────────────────────────────────────

    def _check_partial_tp(self, pos: ManagedPosition, price: float) -> Optional[Dict]:
        entry = pos.entry_price
        tp = pos.take_profit
        partial_pct = settings.PARTIAL_TP_PCT / 100

        # First TP at halfway between entry and full TP
        tp1 = entry + (tp - entry) * 0.5 if pos.direction == "long" else entry - (entry - tp) * 0.5

        hit = price >= tp1 if pos.direction == "long" else price <= tp1
        if hit:
            close_qty = pos.remaining_quantity * partial_pct
            pos.remaining_quantity -= close_qty
            pos.partial_tp_done = True
            return {
                "action": "close_partial",
                "symbol": pos.symbol,
                "quantity": close_qty,
                "reason": "partial_tp",
            }

        return None

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _tp_hit(self, pos: ManagedPosition, price: float) -> bool:
        if pos.direction == "long":
            return price >= pos.take_profit
        return price <= pos.take_profit

    def _sl_hit(self, pos: ManagedPosition, price: float) -> bool:
        if pos.direction == "long":
            return price <= pos.stop_loss
        return price >= pos.stop_loss

    def _pnl_pct(self, pos: ManagedPosition, price: float) -> float:
        if pos.direction == "long":
            return (price - pos.entry_price) / pos.entry_price * 100
        return (pos.entry_price - price) / pos.entry_price * 100

    # ─── Drawdown Protection ─────────────────────────────────────────────────

    def check_drawdown_protection(
        self, current_equity: float, peak_equity: float, current_leverage: int
    ) -> Tuple[int, Optional[str]]:
        """
        Returns (recommended_leverage, alert_message).
        Reduces leverage as drawdown increases.
        """
        if peak_equity <= 0:
            return current_leverage, None

        dd_pct = (peak_equity - current_equity) / peak_equity * 100

        alert = None
        new_leverage = current_leverage

        if dd_pct >= settings.DRAWDOWN_ALERT_PCT:
            alert = f"⚠️ Drawdown alert: {dd_pct:.1f}% from peak equity"

        if dd_pct >= settings.AUTO_REDUCE_LEVERAGE_DD_PCT:
            # Reduce leverage proportionally
            reduction = 1 - (dd_pct / 20)  # 0% dd=full leverage, 20% dd=50% leverage
            new_leverage = max(settings.MIN_LEVERAGE, int(current_leverage * reduction))
            if new_leverage < current_leverage:
                alert = (alert or "") + f"\n🔽 Auto-reducing leverage to {new_leverage}x"

        return new_leverage, alert
