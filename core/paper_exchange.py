"""
Paper Trading Engine
Fetches REAL market data/prices from XT.com (public endpoints, no API key needed)
but simulates order execution against a virtual balance.
This lets the user test strategies risk-free before switching to live mode.
"""
import ccxt.async_support as ccxt
import asyncio
from typing import Optional, Dict, List
from datetime import datetime
from loguru import logger

from core.exchange_interface import ExchangeInterface
from config.settings import settings


class PaperPosition:
    """Represents one simulated open position"""
    def __init__(self, symbol: str, side: str, amount: float, entry_price: float,
                 leverage: int, stop_loss: Optional[float], take_profit: Optional[float]):
        self.symbol = symbol
        self.side = side              # 'buy' (long) or 'sell' (short)
        self.amount = amount          # contract quantity
        self.entry_price = entry_price
        self.leverage = leverage
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.opened_at = datetime.utcnow()
        self.trade_id: Optional[int] = None  # linked DB Trade.id

    @property
    def direction(self) -> str:
        return "long" if self.side == "buy" else "short"

    def unrealized_pnl(self, current_price: float) -> float:
        if self.direction == "long":
            return (current_price - self.entry_price) * self.amount
        else:
            return (self.entry_price - current_price) * self.amount

    def to_position_dict(self, current_price: float) -> Dict:
        """Mimic CCXT's position dict format for compatibility with the rest of the bot"""
        pnl = self.unrealized_pnl(current_price)
        contracts = self.amount if self.direction == "long" else -self.amount
        return {
            "symbol": self.symbol,
            "contracts": contracts,
            "entryPrice": self.entry_price,
            "markPrice": current_price,
            "unrealizedPnl": pnl,
            "leverage": self.leverage,
            "side": self.direction,
            "stopLoss": self.stop_loss,
            "takeProfit": self.take_profit,
        }


class PaperExchange(ExchangeInterface):
    """
    Simulated exchange. Uses XT.com's PUBLIC market data (real prices, no auth needed)
    but all orders/balance/positions are virtual, tracked in memory + DB.
    """

    FEE_RATE = 0.0005  # 0.05% taker fee simulation (typical futures taker fee)

    def __init__(self, starting_balance: float = None):
        self.market_data_client: Optional[ccxt.xt] = None
        self.balance_usdt = starting_balance or settings.PAPER_STARTING_BALANCE
        self.starting_balance = self.balance_usdt
        self.positions: Dict[str, PaperPosition] = {}  # symbol -> position
        self._lock = asyncio.Lock()

    async def connect(self) -> bool:
        try:
            # Public client only — no API keys needed for market data
            self.market_data_client = ccxt.xt({"enableRateLimit": True, "options": {"defaultType": "swap"}})
            await self.market_data_client.load_markets()
            logger.info(
                f"✅ [PAPER] Connected to XT.com market data | "
                f"Virtual balance: {self.balance_usdt:.2f} USDT"
            )
            return True
        except Exception as e:
            logger.error(f"❌ [PAPER] Market data connection failed: {e}")
            return False

    async def disconnect(self):
        if self.market_data_client:
            await self.market_data_client.close()

    async def get_balance(self) -> Dict:
        used = sum(
            (pos.amount * pos.entry_price) / pos.leverage
            for pos in self.positions.values()
        )
        return {
            "USDT": round(self.balance_usdt - used, 2),
            "total": round(self.balance_usdt, 2),
            "used": round(used, 2),
        }

    async def get_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200) -> List:
        try:
            return await self.market_data_client.fetch_ohlcv(symbol, timeframe, limit=limit)
        except Exception as e:
            logger.error(f"[PAPER] OHLCV fetch error for {symbol}: {e}")
            return []

    async def get_ticker(self, symbol: str) -> Dict:
        try:
            return await self.market_data_client.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"[PAPER] Ticker fetch error: {e}")
            return {}

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        # No-op in paper mode, leverage is just stored with the position
        return True

    async def place_order(
        self, symbol: str, side: str, amount: float,
        order_type: str = "market", price: Optional[float] = None,
        stop_loss: Optional[float] = None, take_profit: Optional[float] = None,
        leverage: int = 10,
    ) -> Optional[Dict]:
        async with self._lock:
            try:
                ticker = await self.get_ticker(symbol)
                fill_price = price or ticker.get("last")
                if not fill_price:
                    logger.error(f"[PAPER] No price available for {symbol}")
                    return None

                position_value = amount * fill_price
                margin_required = position_value / leverage
                fee = position_value * self.FEE_RATE

                available = (await self.get_balance())["USDT"]
                if margin_required + fee > available:
                    logger.warning(
                        f"[PAPER] Insufficient virtual balance for {symbol}: "
                        f"need {margin_required + fee:.2f}, have {available:.2f}"
                    )
                    return None

                self.balance_usdt -= fee  # deduct fee immediately

                position = PaperPosition(
                    symbol=symbol, side=side, amount=amount, entry_price=fill_price,
                    leverage=leverage, stop_loss=stop_loss, take_profit=take_profit,
                )
                self.positions[symbol] = position

                logger.info(
                    f"✅ [PAPER] Order filled: {side.upper()} {amount:.6f} {symbol} "
                    f"@ {fill_price:.4f} | leverage {leverage}x | fee {fee:.4f}"
                )

                return {
                    "id": f"paper_{symbol}_{int(datetime.utcnow().timestamp())}",
                    "symbol": symbol,
                    "side": side,
                    "amount": amount,
                    "price": fill_price,
                    "status": "closed",  # filled immediately (market order simulation)
                    "fee": {"cost": fee, "currency": "USDT"},
                }
            except Exception as e:
                logger.error(f"❌ [PAPER] Order simulation failed: {e}")
                return None

    async def get_open_positions(self) -> List[Dict]:
        results = []
        for symbol, pos in self.positions.items():
            ticker = await self.get_ticker(symbol)
            current_price = ticker.get("last", pos.entry_price)
            results.append(pos.to_position_dict(current_price))
        return results

    async def close_position(self, symbol: str, side: str, amount: float) -> Optional[Dict]:
        async with self._lock:
            position = self.positions.get(symbol)
            if not position:
                logger.warning(f"[PAPER] No open position found for {symbol}")
                return None

            ticker = await self.get_ticker(symbol)
            exit_price = ticker.get("last", position.entry_price)

            pnl = position.unrealized_pnl(exit_price)
            position_value = position.amount * exit_price
            fee = position_value * self.FEE_RATE

            self.balance_usdt += pnl - fee
            del self.positions[symbol]

            logger.info(
                f"🔚 [PAPER] Position closed: {symbol} | PnL: {pnl:.2f} USDT "
                f"(fee {fee:.4f}) | New balance: {self.balance_usdt:.2f}"
            )

            return {
                "symbol": symbol,
                "exit_price": exit_price,
                "pnl": pnl,
                "fee": fee,
            }

    async def get_symbols(self, quote: str = "USDT") -> List[str]:
        try:
            markets = await self.market_data_client.load_markets()
            return [
                sym for sym, m in markets.items()
                if m.get("quote") == quote and m.get("type") == "swap" and m.get("active")
            ]
        except Exception as e:
            logger.error(f"[PAPER] Symbols fetch error: {e}")
            return []

    async def get_symbols_by_volume(self, quote: str = "USDT", top_n: int = 8) -> List[str]:
        try:
            symbols = await self.get_symbols(quote)
            tickers = await self.market_data_client.fetch_tickers(symbols)
            ranked = sorted(
                tickers.items(),
                key=lambda kv: kv[1].get("quoteVolume", 0) or 0,
                reverse=True,
            )
            return [sym for sym, _ in ranked[:top_n]]
        except Exception as e:
            logger.error(f"[PAPER] Volume ranking error: {e}")
            return []

    # ─── Paper-specific helpers ────────────────────────────────────────────

    def reset(self, new_balance: float = None):
        """Reset paper account to a fresh virtual balance"""
        self.balance_usdt = new_balance or settings.PAPER_STARTING_BALANCE
        self.starting_balance = self.balance_usdt
        self.positions.clear()
        logger.info(f"🔄 [PAPER] Account reset to {self.balance_usdt:.2f} USDT")

    async def check_sl_tp_triggers(self) -> List[Dict]:
        """
        Check all open paper positions for SL/TP hits.
        Returns list of triggered closures (symbol, reason).
        Should be called periodically by the bot's monitor loop.
        """
        triggered = []
        for symbol, pos in list(self.positions.items()):
            ticker = await self.get_ticker(symbol)
            price = ticker.get("last")
            if not price:
                continue

            if pos.direction == "long":
                if pos.stop_loss and price <= pos.stop_loss:
                    triggered.append({"symbol": symbol, "reason": "sl_hit", "price": price})
                elif pos.take_profit and price >= pos.take_profit:
                    triggered.append({"symbol": symbol, "reason": "tp_hit", "price": price})
            else:
                if pos.stop_loss and price >= pos.stop_loss:
                    triggered.append({"symbol": symbol, "reason": "sl_hit", "price": price})
                elif pos.take_profit and price <= pos.take_profit:
                    triggered.append({"symbol": symbol, "reason": "tp_hit", "price": price})

        return triggered
