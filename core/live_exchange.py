"""
Live Exchange Connector — XT.com
Handles all REAL trading communication with XT.com via CCXT.
Only used when TRADING_MODE=live.
"""
import ccxt.async_support as ccxt
import asyncio
from typing import Optional, Dict, List
from loguru import logger

from core.exchange_interface import ExchangeInterface
from config.settings import settings


class LiveExchange(ExchangeInterface):
    """Real trading on XT.com — uses real money. Use with caution."""

    def __init__(self):
        self.exchange: Optional[ccxt.xt] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> bool:
        try:
            self.exchange = ccxt.xt({
                "apiKey": settings.XT_API_KEY,
                "secret": settings.XT_SECRET_KEY,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "swap",  # USDT-margined futures
                    "adjustForTimeDifference": True,
                },
            })
            await self.exchange.load_markets()
            balance = await self.exchange.fetch_balance()
            usdt = balance.get("USDT", {}).get("free", 0)
            logger.info(f"✅ [LIVE] Connected to XT.com | Free balance: {usdt:.2f} USDT")
            return True
        except Exception as e:
            logger.error(f"❌ [LIVE] XT.com connection failed: {e}")
            return False

    async def disconnect(self):
        if self.exchange:
            await self.exchange.close()

    async def get_balance(self) -> Dict:
        async with self._lock:
            try:
                balance = await self.exchange.fetch_balance()
                usdt = balance.get("USDT", {})
                return {
                    "USDT": usdt.get("free", 0),
                    "total": usdt.get("total", 0),
                    "used": usdt.get("used", 0),
                }
            except Exception as e:
                logger.error(f"[LIVE] Balance fetch error: {e}")
                return {"USDT": 0, "total": 0, "used": 0}

    async def get_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200) -> List:
        try:
            return await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        except Exception as e:
            logger.error(f"[LIVE] OHLCV fetch error for {symbol}: {e}")
            return []

    async def get_ticker(self, symbol: str) -> Dict:
        try:
            return await self.exchange.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"[LIVE] Ticker fetch error: {e}")
            return {}

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        try:
            await self.exchange.set_leverage(leverage, symbol)
            return True
        except Exception as e:
            logger.error(f"[LIVE] Set leverage error: {e}")
            return False

    async def place_order(
        self, symbol: str, side: str, amount: float,
        order_type: str = "market", price: Optional[float] = None,
        stop_loss: Optional[float] = None, take_profit: Optional[float] = None,
        leverage: int = 10,
    ) -> Optional[Dict]:
        async with self._lock:
            try:
                await self.set_leverage(symbol, leverage)
                params = {}
                if stop_loss:
                    params["stopLoss"] = {"triggerPrice": stop_loss, "type": "market"}
                if take_profit:
                    params["takeProfit"] = {"triggerPrice": take_profit, "type": "market"}

                order = await self.exchange.create_order(
                    symbol=symbol, type=order_type, side=side,
                    amount=amount, price=price, params=params
                )
                logger.info(f"✅ [LIVE] Order placed: {side.upper()} {amount} {symbol}")
                return order
            except Exception as e:
                logger.error(f"❌ [LIVE] Order placement failed: {e}")
                return None

    async def get_open_positions(self) -> List[Dict]:
        try:
            positions = await self.exchange.fetch_positions()
            return [p for p in positions if p.get("contracts", 0) != 0]
        except Exception as e:
            logger.error(f"[LIVE] Positions fetch error: {e}")
            return []

    async def close_position(self, symbol: str, side: str, amount: float) -> Optional[Dict]:
        close_side = "sell" if side == "long" else "buy"
        return await self.place_order(symbol, close_side, amount, "market")

    async def get_symbols(self, quote: str = "USDT") -> List[str]:
        try:
            markets = await self.exchange.load_markets()
            return [
                sym for sym, m in markets.items()
                if m.get("quote") == quote and m.get("type") == "swap" and m.get("active")
            ]
        except Exception as e:
            logger.error(f"[LIVE] Symbols fetch error: {e}")
            return []

    async def get_symbols_by_volume(self, quote: str = "USDT", top_n: int = 8) -> List[str]:
        """Fetch all symbols, rank by 24h quote volume, return top N"""
        try:
            symbols = await self.get_symbols(quote)
            tickers = await self.exchange.fetch_tickers(symbols)
            ranked = sorted(
                tickers.items(),
                key=lambda kv: kv[1].get("quoteVolume", 0) or 0,
                reverse=True,
            )
            return [sym for sym, _ in ranked[:top_n]]
        except Exception as e:
            logger.error(f"[LIVE] Volume ranking error: {e}")
            return []
