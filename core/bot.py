"""Main Trading Bot Orchestrator v4 — SuperTrend + Price Action + Elliott Wave (no ML)"""
import asyncio
from typing import List, Dict, Optional
from loguru import logger
from datetime import datetime, timedelta

from core.exchange_factory import create_exchange
from core.indicators import IndicatorEngine
from strategies.engine import StrategyEngine, assess_market_regime
from risk.manager import RiskManager
from risk.position_manager import PositionManager, ManagedPosition
from filters.smart_filters import FilterEngine
from bot.telegram_bot import TelegramNotifier
from config.settings import settings
from db.session import (
    init_db, create_trade, close_trade, record_equity_snapshot,
    log_system_event,
)


class TradingBotV3:
    def __init__(self):
        self.exchange = create_exchange()
        self.strategy = StrategyEngine()
        self.risk = RiskManager()
        self.pos_manager = PositionManager()
        self.filters = FilterEngine()
        self.telegram = TelegramNotifier()
        self.running = False
        self.symbols: List[str] = []
        self._peak_equity = settings.PAPER_STARTING_BALANCE
        self._trade_id_map: Dict[str, int] = {}

    async def start(self):
        logger.info("🚀 Starting Trading Bot v3")
        await init_db()
        await log_system_event("startup", f"Bot v3 starting in {settings.TRADING_MODE} mode")

        connected = await self.exchange.connect()
        if not connected:
            logger.error("Exchange connection failed")
            return

        self.symbols = await self._select_symbols()
        await self.telegram.start()

        bal = await self.exchange.get_balance()
        self._peak_equity = bal.get("total", settings.PAPER_STARTING_BALANCE)

        await self.telegram.send_message(
            f"🚀 *Bot v3 Started*\n"
            f"Mode: `{settings.TRADING_MODE.upper()}`\n"
            f"Balance: `${bal.get('USDT', 0):.2f}`\n"
            f"Symbols: `{len(self.symbols)}`\n"
            f"Strategy: `SuperTrend + Price Action + Elliott Wave`"
        )

        self.running = True
        await asyncio.gather(
            self._trading_loop(),
            self._position_monitor_loop(),
            self._equity_snapshot_loop(),
            self._daily_reset_loop(),
        )

    async def _trading_loop(self):
        while self.running:
            try:
                bal = await self.exchange.get_balance()
                balance_usdt = bal.get("USDT", 0)
                positions = await self.exchange.get_open_positions()
                self.risk.update_open_positions(len(positions))

                can_trade, reason = self.risk.check_can_trade(balance_usdt)
                if not can_trade:
                    logger.warning(f"⛔ {reason}")
                    await asyncio.sleep(60)
                    continue

                tasks = [self._analyze_symbol(sym, balance_usdt, positions) for sym in self.symbols]
                await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Trading loop error: {e}")
                await asyncio.sleep(30)

    async def _analyze_symbol(self, symbol: str, balance_usdt: float, open_positions: List[Dict]):
        try:
            if any(p.get("symbol") == symbol for p in open_positions):
                return

            ohlcv_15m = await self.exchange.get_ohlcv(symbol, "15m", 300)
            ohlcv_4h  = await self.exchange.get_ohlcv(symbol, "4h", 200)

            if not ohlcv_15m or len(ohlcv_15m) < 100:
                return

            funding_rate = await self.exchange.get_funding_rate(symbol)
            eng_15m = IndicatorEngine(
                ohlcv_15m, funding_rate=funding_rate,
                supertrend_atr_len=settings.SUPERTREND_ATR_LENGTH,
                supertrend_factor=settings.SUPERTREND_FACTOR,
                pa_swing_len=settings.PRICE_ACTION_SWING_LENGTH,
            )
            eng_4h  = IndicatorEngine(ohlcv_4h)
            ind_15m = eng_15m.get_latest()
            ind_4h  = eng_4h.get_latest()

            result = self.strategy.analyze_indicators(ind_15m)
            regime = assess_market_regime(ind_15m)

            if not result:
                return
            direction, confidence, reason_tag = result

            if confidence < settings.STRATEGY_MIN_CONFIDENCE:
                return

            ok, reason = await self.filters.can_enter(symbol, direction, ind_15m, ind_4h, open_positions)
            if not ok:
                logger.debug(f"🚫 {symbol} filtered: {reason}")
                return

            logger.info(f"📡 {symbol} {direction.upper()} | confidence={confidence:.0%} | {reason_tag}")

            ticker = await self.exchange.get_ticker(symbol)
            entry  = ticker.get("last", 0)
            if not entry:
                return

            atr         = ind_15m.get("atr") or entry * 0.01
            regime_name = regime.get("regime", "ranging")
            risk_mult   = regime.get("risk_multiplier", 1.0)

            sl_tp    = self.risk.calculate_sl_tp(entry, direction, atr, regime=regime_name)
            pos_size = self.risk.calculate_position_size(
                balance=balance_usdt, entry_price=entry,
                stop_loss_price=sl_tp["stop_loss"],
                risk_multiplier=risk_mult, confidence=confidence,
            )
            leverage = self.risk.get_dynamic_leverage(confidence, regime_name, ind_15m.get("atr_pct", 1.0) or 1.0)

            bal_total = (await self.exchange.get_balance()).get("total", balance_usdt)
            self._peak_equity = max(self._peak_equity, bal_total)
            leverage, dd_alert = self.pos_manager.check_drawdown_protection(bal_total, self._peak_equity, leverage)
            if dd_alert:
                await self.telegram.send_message(dd_alert)

            if pos_size["quantity"] <= 0:
                return

            side  = "buy" if direction == "long" else "sell"
            order = await self.exchange.place_order(
                symbol=symbol, side=side, amount=pos_size["quantity"],
                stop_loss=sl_tp["stop_loss"], take_profit=sl_tp["take_profit"], leverage=leverage,
            )
            if not order:
                return

            managed_pos = ManagedPosition(
                symbol=symbol, direction=direction, entry_price=entry,
                quantity=pos_size["quantity"], leverage=leverage,
                stop_loss=sl_tp["stop_loss"], take_profit=sl_tp["take_profit"],
            )
            self.pos_manager.register(managed_pos)

            db_trade = await create_trade(
                symbol=symbol, direction=direction, mode=settings.TRADING_MODE,
                entry_price=entry, stop_loss=sl_tp["stop_loss"], take_profit=sl_tp["take_profit"],
                quantity=pos_size["quantity"], position_value_usdt=pos_size["position_value_usdt"],
                leverage=leverage, status="open",
                strategy_tag=f"st_pa_ew:{reason_tag}",
                ai_confidence=confidence, market_regime=regime_name,
            )
            self._trade_id_map[symbol] = db_trade.id
            managed_pos.trade_db_id = db_trade.id

            await self.telegram.send_trade_opened(
                symbol=symbol, direction=direction, entry=entry,
                sl=sl_tp["stop_loss"], tp=sl_tp["take_profit"],
                size=pos_size["position_value_usdt"], leverage=leverage,
                confidence=confidence,
                reason=f"{reason_tag} regime={regime_name}",
                mode=settings.TRADING_MODE,
            )

        except Exception as e:
            logger.error(f"Analyze {symbol} error: {e}")

    async def _position_monitor_loop(self):
        while self.running:
            try:
                if settings.is_paper and hasattr(self.exchange, "check_sl_tp_triggers"):
                    triggers = await self.exchange.check_sl_tp_triggers()
                    for trig in triggers:
                        await self._execute_close(trig["symbol"], trig["reason"])

                positions = await self.exchange.get_open_positions()
                for pos_dict in positions:
                    symbol        = pos_dict.get("symbol")
                    current_price = pos_dict.get("markPrice", 0)
                    managed       = self.pos_manager.get(symbol)

                    if managed and current_price:
                        actions = await self.pos_manager.check_position(managed, current_price)
                        for action in actions:
                            if action["action"] == "close_full":
                                await self._execute_close(symbol, action["reason"])
                            elif action["action"] == "close_partial":
                                await self._execute_partial_close(symbol, action["quantity"], action["reason"])
                            elif action["action"] == "update_sl":
                                logger.info(f"📍 SL updated: {symbol} → {action['new_sl']:.4f} ({action['reason']})")

                await asyncio.sleep(15)
            except Exception as e:
                logger.error(f"Position monitor error: {e}")
                await asyncio.sleep(15)

    async def _execute_close(self, symbol: str, reason: str):
        try:
            positions = await self.exchange.get_open_positions()
            pos_dict  = next((p for p in positions if p.get("symbol") == symbol), None)
            if not pos_dict:
                self.pos_manager.unregister(symbol)
                return

            direction = "long" if pos_dict.get("contracts", 0) > 0 else "short"
            entry     = pos_dict.get("entryPrice", 0)
            amount    = abs(pos_dict.get("contracts", 0))

            result = await self.exchange.close_position(symbol, direction, amount)
            if not result:
                return

            exit_price = result.get("exit_price", pos_dict.get("markPrice", entry))
            pnl        = result.get("pnl", pos_dict.get("unrealizedPnl", 0))
            pnl_pct    = (pnl / (entry * amount / pos_dict.get("leverage", 10))) * 100 if entry and amount else 0

            self.risk.record_trade(pnl, symbol, direction)
            self.pos_manager.unregister(symbol)

            trade_id = self._trade_id_map.pop(symbol, None)
            if trade_id:
                await close_trade(trade_id, exit_price, pnl, pnl_pct, reason)

            await self.telegram.send_trade_closed(
                symbol=symbol, direction=direction, entry=entry, exit_price=exit_price,
                pnl=pnl, pnl_pct=pnl_pct, reason=reason, mode=settings.TRADING_MODE,
            )
        except Exception as e:
            logger.error(f"Close error {symbol}: {e}")

    async def _execute_partial_close(self, symbol: str, quantity: float, reason: str):
        try:
            positions = await self.exchange.get_open_positions()
            pos_dict  = next((p for p in positions if p.get("symbol") == symbol), None)
            if not pos_dict:
                return
            direction = "long" if pos_dict.get("contracts", 0) > 0 else "short"
            result = await self.exchange.close_position(symbol, direction, quantity)
            if result:
                pnl = result.get("pnl", 0)
                logger.info(f"✂️ Partial close {symbol}: {reason} | PnL: ${pnl:.2f}")
                await self.telegram.send_message(
                    f"✂️ *Partial TP* `{symbol}`\nClosed: `{quantity:.4f}` | PnL: `${pnl:.2f}`\nReason: _{reason}_"
                )
        except Exception as e:
            logger.error(f"Partial close error {symbol}: {e}")

    async def _equity_snapshot_loop(self):
        while self.running:
            try:
                bal        = await self.exchange.get_balance()
                positions  = await self.exchange.get_open_positions()
                unrealized = sum(p.get("unrealizedPnl", 0) for p in positions)
                equity     = bal.get("total", 0) + unrealized
                self._peak_equity = max(self._peak_equity, equity)
                await record_equity_snapshot(
                    mode=settings.TRADING_MODE, balance=bal.get("total", 0),
                    equity=equity, open_positions=len(positions),
                )
                await asyncio.sleep(300)
            except Exception as e:
                logger.error(f"Equity snapshot error: {e}")
                await asyncio.sleep(300)

    async def _daily_reset_loop(self):
        while self.running:
            now  = datetime.utcnow()
            nxt  = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            await asyncio.sleep((nxt - now).total_seconds())
            self.risk.resume_trading()
            await log_system_event("daily_reset", "Daily stats reset")
            await self.telegram.send_message("🌅 *New Trading Day* — stats reset")

    async def _select_symbols(self) -> List[str]:
        try:
            syms = await self.exchange.get_symbols_by_volume("USDT", settings.MAX_SYMBOLS_TRADED)
            if syms:
                return syms
        except Exception as e:
            logger.error(f"Symbol selection error: {e}")
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]

    async def stop(self):
        self.running = False
        await log_system_event("shutdown", "Bot stopped")
        await self.telegram.send_message("🛑 *Bot Stopped*")
        await self.exchange.disconnect()
