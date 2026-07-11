"""
Smart Signal Filters v3
Removes weak signals before they reach the strategy engine.
Filters: Correlation, Volatility, News, Market Structure
"""
import asyncio
import aiohttp
import feedparser
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
from loguru import logger
from textblob import TextBlob

from config.settings import settings


class CorrelationFilter:
    """
    Prevents opening highly-correlated positions simultaneously.
    E.g., BTC and ETH are ~0.9 correlated — don't hold both Long at same time.
    """

    def __init__(self, threshold: float = 0.85):
        self.threshold = threshold
        self._price_history: Dict[str, List[float]] = {}

    def update_price(self, symbol: str, price: float):
        if symbol not in self._price_history:
            self._price_history[symbol] = []
        self._price_history[symbol].append(price)
        if len(self._price_history[symbol]) > 100:
            self._price_history[symbol].pop(0)

    def are_correlated(self, sym1: str, sym2: str) -> bool:
        import numpy as np
        h1 = self._price_history.get(sym1, [])
        h2 = self._price_history.get(sym2, [])
        if len(h1) < 20 or len(h2) < 20:
            return False
        min_len = min(len(h1), len(h2))
        try:
            corr = float(np.corrcoef(h1[-min_len:], h2[-min_len:])[0, 1])
            return abs(corr) >= self.threshold
        except Exception:
            return False

    def can_open(self, symbol: str, direction: str, open_positions: List[Dict]) -> Tuple[bool, str]:
        """Check if opening this position would over-concentrate correlated assets"""
        for pos in open_positions:
            pos_sym = pos.get("symbol", "")
            pos_dir = pos.get("side", "long")
            if pos_sym == symbol:
                continue
            if self.are_correlated(symbol, pos_sym) and pos_dir == direction:
                return False, f"Correlated with open position {pos_sym} ({direction})"
        return True, "OK"


class VolatilityFilter:
    """
    Avoids trading in extremely calm or extremely chaotic markets.
    Calm market = no momentum → signals are unreliable.
    """

    def can_trade(self, atr_pct: float, bb_width: float) -> Tuple[bool, str]:
        if atr_pct < settings.MIN_ATR_PCT:
            return False, f"Market too calm: ATR {atr_pct:.2f}% < {settings.MIN_ATR_PCT}%"
        if atr_pct > 8.0:
            return False, f"Market too volatile: ATR {atr_pct:.2f}% > 8%"
        if bb_width < 0.005:
            return False, f"BB squeeze detected — waiting for breakout"
        return True, "OK"


class NewsSentimentFilter:
    """
    Fetches crypto news headlines, runs sentiment analysis (TextBlob),
    and pauses trading before/after major negative/positive news events.
    """

    def __init__(self):
        self._last_fetch: Optional[datetime] = None
        self._cache_minutes = 15
        self._last_sentiment: float = 0.0  # -1 to 1
        self._pause_until: Optional[datetime] = None

    async def fetch_sentiment(self) -> float:
        """Fetch latest crypto news and compute average sentiment score"""
        if self._last_fetch and (datetime.utcnow() - self._last_fetch).seconds < self._cache_minutes * 60:
            return self._last_sentiment

        try:
            feeds = [
                "https://feeds.feedburner.com/CoinDesk",
                "https://cointelegraph.com/rss",
            ]
            scores = []
            for url in feeds:
                try:
                    feed = feedparser.parse(url)
                    for entry in feed.entries[:5]:
                        title = entry.get("title", "")
                        blob = TextBlob(title)
                        scores.append(blob.sentiment.polarity)
                except Exception:
                    pass

            self._last_sentiment = sum(scores) / len(scores) if scores else 0.0
            self._last_fetch = datetime.utcnow()

            if self._last_sentiment < -0.4:
                self._pause_until = datetime.utcnow() + timedelta(minutes=settings.NEWS_PAUSE_MINUTES)
                logger.warning(f"📰 Negative news detected (sentiment={self._last_sentiment:.2f}) — pausing {settings.NEWS_PAUSE_MINUTES}min")

            return self._last_sentiment

        except Exception as e:
            logger.error(f"News fetch error: {e}")
            return 0.0

    async def can_trade(self) -> Tuple[bool, str]:
        if not settings.NEWS_FILTER_ENABLED:
            return True, "OK"

        if self._pause_until and datetime.utcnow() < self._pause_until:
            remaining = (self._pause_until - datetime.utcnow()).seconds // 60
            return False, f"News pause active ({remaining}min remaining)"

        sentiment = await self.fetch_sentiment()

        if sentiment < -0.5:
            return False, f"Extreme negative news sentiment: {sentiment:.2f}"

        return True, f"News OK (sentiment={sentiment:.2f})"


class MarketStructureFilter:
    """
    Only trades in the direction of higher-timeframe market structure.
    Uses 4h Heikin Ashi trend + Ichimoku cloud position.
    """

    def can_trade_direction(self, direction: str, ind_4h: Dict) -> Tuple[bool, str]:
        if not ind_4h:
            return True, "OK (no 4h data)"

        ichi_above = ind_4h.get("ichi_above_cloud", False)
        ichi_below = ind_4h.get("ichi_below_cloud", False)
        ha_bullish = ind_4h.get("ha_bullish", None)
        supertrend_dir = ind_4h.get("supertrend_dir", 0)

        # Strong bearish structure: don't go long
        if direction == "long":
            if ichi_below and not ha_bullish and supertrend_dir == -1:
                return False, "4H structure bearish — no longs"
        # Strong bullish structure: don't go short
        elif direction == "short":
            if ichi_above and ha_bullish and supertrend_dir == 1:
                return False, "4H structure bullish — no shorts"

        return True, "OK"


class WhaleFilter:
    """
    Monitors large on-chain transactions.
    Large whale selling → avoid longs; large whale buying → avoid shorts.
    Uses Whale Alert RSS feed (free tier).
    """

    def __init__(self):
        self._whale_signals: List[Dict] = []
        self._last_fetch: Optional[datetime] = None

    async def fetch_whale_activity(self):
        if self._last_fetch and (datetime.utcnow() - self._last_fetch).seconds < 300:
            return

        try:
            # Whale Alert RSS (free, no API key needed for basic data)
            url = "https://whale-alert.io/rss"
            feed = feedparser.parse(url)
            signals = []
            for entry in feed.entries[:10]:
                title = entry.get("title", "").lower()
                if "transfer" in title or "move" in title:
                    # Parse direction from title heuristics
                    if "to exchange" in title:
                        signals.append({"type": "sell_pressure", "ts": datetime.utcnow()})
                    elif "from exchange" in title:
                        signals.append({"type": "buy_pressure", "ts": datetime.utcnow()})
            self._whale_signals = signals
            self._last_fetch = datetime.utcnow()
            if signals:
                logger.info(f"🐋 Whale activity detected: {len(signals)} signals")
        except Exception:
            pass

    def get_whale_bias(self) -> Optional[str]:
        """Returns 'bearish', 'bullish', or None"""
        now = datetime.utcnow()
        recent = [s for s in self._whale_signals if (now - s["ts"]).seconds < 1800]
        if not recent:
            return None
        sell_count = sum(1 for s in recent if s["type"] == "sell_pressure")
        buy_count = sum(1 for s in recent if s["type"] == "buy_pressure")
        if sell_count > buy_count * 2:
            return "bearish"
        if buy_count > sell_count * 2:
            return "bullish"
        return None

    def can_trade_direction(self, direction: str) -> Tuple[bool, str]:
        bias = self.get_whale_bias()
        if bias == "bearish" and direction == "long":
            return False, "Whale selling detected — avoiding longs"
        if bias == "bullish" and direction == "short":
            return False, "Whale buying detected — avoiding shorts"
        return True, "OK"


class FilterEngine:
    """Aggregates all filters into one can_trade() call"""

    def __init__(self):
        self.correlation = CorrelationFilter(threshold=settings.CORRELATION_THRESHOLD)
        self.volatility = VolatilityFilter()
        self.news = NewsSentimentFilter()
        self.market_structure = MarketStructureFilter()
        self.whale = WhaleFilter()

    async def can_enter(
        self, symbol: str, direction: str,
        ind_15m: Dict, ind_4h: Dict,
        open_positions: List[Dict],
    ) -> Tuple[bool, str]:
        """Run all filters. Returns (True, 'OK') only if ALL filters pass."""

        # 1. Volatility
        if settings.VOLATILITY_FILTER_ENABLED:
            ok, reason = self.volatility.can_trade(
                ind_15m.get("atr_pct", 1.0) or 1.0,
                ind_15m.get("bb_width", 0.02) or 0.02,
            )
            if not ok:
                return False, f"[VolFilter] {reason}"

        # 2. Correlation
        if settings.CORRELATION_FILTER_ENABLED:
            ok, reason = self.correlation.can_open(symbol, direction, open_positions)
            if not ok:
                return False, f"[CorrFilter] {reason}"

        # 3. News sentiment
        if settings.NEWS_FILTER_ENABLED:
            ok, reason = await self.news.can_trade()
            if not ok:
                return False, f"[NewsFilter] {reason}"

        # 4. Market structure (4H)
        ok, reason = self.market_structure.can_trade_direction(direction, ind_4h)
        if not ok:
            return False, f"[StructFilter] {reason}"

        # 5. Whale activity
        await self.whale.fetch_whale_activity()
        ok, reason = self.whale.can_trade_direction(direction)
        if not ok:
            return False, f"[WhaleFilter] {reason}"

        return True, "ALL_FILTERS_PASSED"
