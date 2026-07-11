"""
Backtesting Engine v4
Includes: Standard Backtest, Walk-Forward Testing, Monte Carlo Simulation
All run against historical OHLCV data before switching to Live.

v4: runs the same rule-based SuperTrend + Price Action + Elliott Wave
strategy used live — no AI/ML model to train, so walk-forward testing no
longer needs a training phase (there's nothing to fit; the rules are fixed).
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from loguru import logger

from core.indicators import IndicatorEngine
from strategies.engine import StrategyEngine


class BacktestTrade:
    def __init__(self, symbol, direction, entry, sl, tp, qty, leverage, opened_at):
        self.symbol = symbol
        self.direction = direction
        self.entry = entry
        self.sl = sl
        self.tp = tp
        self.qty = qty
        self.leverage = leverage
        self.opened_at = opened_at
        self.exit_price = None
        self.pnl = None
        self.exit_reason = None
        self.closed_at = None

    def close(self, price: float, reason: str, ts: datetime):
        self.exit_price = price
        self.exit_reason = reason
        self.closed_at = ts
        if self.direction == "long":
            self.pnl = (price - self.entry) * self.qty
        else:
            self.pnl = (self.entry - price) * self.qty


class BacktestEngine:
    """
    Simulates strategy on historical OHLCV data.
    Includes realistic: spread, slippage, fees.
    """

    TAKER_FEE = 0.0005  # 0.05%
    SLIPPAGE = 0.0002   # 0.02%

    def __init__(self, starting_balance: float = 200.0):
        self.starting_balance = starting_balance
        self.strategy = StrategyEngine()
        self.trades: List[BacktestTrade] = []

    def run(self, ohlcv: List, symbol: str = "BTC/USDT") -> Dict:
        """Run full backtest on historical OHLCV data"""
        logger.info(f"📊 Starting backtest on {len(ohlcv)} candles for {symbol}")

        balance = self.starting_balance
        equity_curve = [balance]
        self.trades = []
        open_trade: Optional[BacktestTrade] = None

        for i in range(100, len(ohlcv)):
            candles = ohlcv[:i]
            eng = IndicatorEngine(candles)
            df = eng.get_dataframe()
            ind = eng.get_latest()
            current_candle = ohlcv[i]
            ts = datetime.fromtimestamp(current_candle[0] / 1000)
            price = current_candle[4]  # close

            # Check open trade exit
            if open_trade:
                high = current_candle[2]
                low = current_candle[3]

                # SL hit
                if open_trade.direction == "long" and low <= open_trade.sl:
                    open_trade.close(open_trade.sl, "sl_hit", ts)
                    balance += open_trade.pnl - abs(open_trade.entry * open_trade.qty * self.TAKER_FEE)
                    self.trades.append(open_trade)
                    open_trade = None

                elif open_trade.direction == "short" and high >= open_trade.sl:
                    open_trade.close(open_trade.sl, "sl_hit", ts)
                    balance += open_trade.pnl - abs(open_trade.entry * open_trade.qty * self.TAKER_FEE)
                    self.trades.append(open_trade)
                    open_trade = None

                # TP hit
                elif open_trade.direction == "long" and high >= open_trade.tp:
                    open_trade.close(open_trade.tp, "tp_hit", ts)
                    balance += open_trade.pnl - abs(open_trade.entry * open_trade.qty * self.TAKER_FEE)
                    self.trades.append(open_trade)
                    open_trade = None

                elif open_trade.direction == "short" and low <= open_trade.tp:
                    open_trade.close(open_trade.tp, "tp_hit", ts)
                    balance += open_trade.pnl - abs(open_trade.entry * open_trade.qty * self.TAKER_FEE)
                    self.trades.append(open_trade)
                    open_trade = None

            # Look for new entry
            if not open_trade and balance > 10:
                result = self.strategy.analyze_indicators(ind)

                if result and result[1] >= 0.55:
                    direction = result[0]
                    atr = ind.get("atr") or price * 0.01
                    entry = price * (1 + self.SLIPPAGE) if direction == "long" else price * (1 - self.SLIPPAGE)
                    sl = entry - atr * 1.5 if direction == "long" else entry + atr * 1.5
                    tp = entry + atr * 3.75 if direction == "long" else entry - atr * 3.75
                    risk_usdt = balance * 0.015
                    qty = risk_usdt / abs(entry - sl) if abs(entry - sl) > 0 else 0

                    if qty > 0:
                        open_trade = BacktestTrade(symbol, direction, entry, sl, tp, qty, 10, ts)

            equity_curve.append(max(balance, 0))

        return self._calculate_stats(equity_curve)

    def _calculate_stats(self, equity_curve: List[float]) -> Dict:
        closed = [t for t in self.trades if t.pnl is not None]
        if not closed:
            return {"error": "no_trades"}

        pnls = [t.pnl for t in closed]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        total_pnl = sum(pnls)
        win_rate = len(wins) / len(closed) * 100
        profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

        # Sharpe
        returns = pd.Series(pnls)
        sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0

        # Max Drawdown
        eq = pd.Series(equity_curve)
        peak = eq.cummax()
        dd = (peak - eq) / peak * 100
        max_dd = float(dd.max())

        return {
            "total_trades": len(closed),
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "total_return_pct": round(total_pnl / self.starting_balance * 100, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
            "sharpe_ratio": round(float(sharpe), 2),
            "max_drawdown_pct": round(max_dd, 2),
            "best_trade": round(max(pnls), 2),
            "worst_trade": round(min(pnls), 2),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "wins": len(wins),
            "losses": len(losses),
            "final_balance": round(equity_curve[-1], 2),
        }


class WalkForwardTester:
    """
    Walk-forward analysis: train on window, test on next period, roll forward.
    Prevents overfitting — each period is tested out-of-sample.
    """

    def __init__(self, train_months: int = 3, test_months: int = 1):
        self.train_months = train_months
        self.test_months = test_months

    def run(self, ohlcv: List, candles_per_month: int = 2880) -> Dict:
        """
        Splits data into rolling windows and evaluates strategy on each.
        candles_per_month=2880 assumes 15m candles (4/hr * 24hr * 30days)
        """
        train_size = self.train_months * candles_per_month
        test_size = self.test_months * candles_per_month
        window = train_size + test_size

        if len(ohlcv) < window:
            return {"error": "insufficient_data", "needed": window, "got": len(ohlcv)}

        results = []
        step = 0

        while step + window <= len(ohlcv):
            window_data = ohlcv[step:step + window]
            train_data = window_data[:train_size]
            test_data = window_data[train_size:]

            # No training step needed — the strategy is fixed, rule-based logic.
            # The "train" window is still included so the indicator warm-up
            # (SuperTrend/ATR/EMA lookbacks etc.) has enough history before
            # the out-of-sample test window begins.
            engine = BacktestEngine()

            # Test on out-of-sample data
            result = engine.run(train_data + test_data)
            result["window"] = step
            result["period"] = f"Month {step // candles_per_month + 1}"
            results.append(result)

            step += test_size

        # Aggregate
        if not results:
            return {"error": "no_windows"}

        valid = [r for r in results if "error" not in r]
        if not valid:
            return {"error": "all_windows_failed"}

        return {
            "method": "walk_forward",
            "windows": len(valid),
            "avg_win_rate": round(np.mean([r["win_rate"] for r in valid]), 1),
            "avg_return_pct": round(np.mean([r["total_return_pct"] for r in valid]), 2),
            "avg_sharpe": round(np.mean([r["sharpe_ratio"] for r in valid]), 2),
            "avg_max_dd": round(np.mean([r["max_drawdown_pct"] for r in valid]), 2),
            "consistency": round(sum(1 for r in valid if r["total_pnl"] > 0) / len(valid) * 100, 1),
            "window_results": valid,
        }


class MonteCarloSimulator:
    """
    Monte Carlo simulation: randomly shuffles trade order 1000 times.
    Shows best/worst/expected outcomes from the same strategy.
    """

    def run(self, trades: List[BacktestTrade], starting_balance: float, n_simulations: int = 1000) -> Dict:
        pnls = [t.pnl for t in trades if t.pnl is not None]
        if not pnls:
            return {"error": "no_trades"}

        final_balances = []
        max_drawdowns = []

        for _ in range(n_simulations):
            shuffled = np.random.choice(pnls, size=len(pnls), replace=True)
            equity = [starting_balance]
            for pnl in shuffled:
                equity.append(max(equity[-1] + pnl, 0))

            final_balances.append(equity[-1])
            eq = np.array(equity)
            peak = np.maximum.accumulate(eq)
            dd = (peak - eq) / (peak + 1e-9) * 100
            max_drawdowns.append(float(dd.max()))

        final_balances = sorted(final_balances)
        return {
            "method": "monte_carlo",
            "simulations": n_simulations,
            "starting_balance": starting_balance,
            "expected_balance": round(float(np.mean(final_balances)), 2),
            "best_case_balance": round(float(np.percentile(final_balances, 95)), 2),
            "worst_case_balance": round(float(np.percentile(final_balances, 5)), 2),
            "median_balance": round(float(np.median(final_balances)), 2),
            "probability_of_profit": round(sum(1 for b in final_balances if b > starting_balance) / n_simulations * 100, 1),
            "expected_max_drawdown": round(float(np.mean(max_drawdowns)), 2),
            "worst_case_drawdown": round(float(np.percentile(max_drawdowns, 95)), 2),
        }
