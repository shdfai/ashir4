"""
Application Settings v3 — Ultra Advanced Trading Bot
"""
from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    # XT.com API
    XT_API_KEY: str = ""
    XT_SECRET_KEY: str = ""

    # Trading mode
    TRADING_MODE: Literal["paper", "live"] = "paper"
    PAPER_STARTING_BALANCE: float = 200.0

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Database
    DATABASE_URL: str = "sqlite:///./trading_bot.db"

    # Trading parameters
    MAX_OPEN_TRADES: int = 10           # AI decides how many, up to this limit
    DEFAULT_LEVERAGE: int = 10
    MAX_LEVERAGE: int = 20
    MIN_LEVERAGE: int = 3
    RISK_PER_TRADE: float = 1.5
    MAX_DAILY_LOSS: float = 5.0
    MIN_BALANCE_USDT: float = 20.0
    PRIMARY_TIMEFRAME: str = "15m"
    CONFIRMATION_TIMEFRAMES: str = "1m,5m,15m,1h,4h"  # all used for multi-TF confirmation
    MAX_SYMBOLS_TRADED: int = 10

    # Position management
    TRAILING_STOP_ENABLED: bool = True
    TRAILING_STOP_PCT: float = 1.0      # trail by 1% from peak
    PARTIAL_TP_ENABLED: bool = True
    PARTIAL_TP_PCT: float = 50.0        # close 50% at first TP
    BREAK_EVEN_ENABLED: bool = True
    BREAK_EVEN_TRIGGER_RR: float = 1.0  # move SL to entry when 1:1 reached

    # Protection
    DRAWDOWN_ALERT_PCT: float = 8.0     # alert at 8% drawdown
    AUTO_REDUCE_LEVERAGE_DD_PCT: float = 5.0  # reduce leverage at 5% drawdown
    TIME_BASED_EXIT_MINUTES: int = 240  # close losing positions after 4h

    # Strategy — SuperTrend + Price Action + Elliott Wave (rule-based, no ML)
    SUPERTREND_ATR_LENGTH: int = 10
    SUPERTREND_FACTOR: float = 2.0
    PRICE_ACTION_SWING_LENGTH: int = 5   # lower = more sensitive BOS/CHoCH detection
    STRATEGY_MIN_CONFIDENCE: float = 0.60

    # External data
    NEWS_FEED_URL: str = "https://cryptopanic.com/api/v1/posts/?auth_token=&kind=news&filter=hot"
    WHALE_ALERT_THRESHOLD_USD: float = 1000000.0  # $1M+ transactions

    # Filters
    CORRELATION_FILTER_ENABLED: bool = True
    CORRELATION_THRESHOLD: float = 0.85
    VOLATILITY_FILTER_ENABLED: bool = True
    MIN_ATR_PCT: float = 0.3            # don't trade if market too calm
    NEWS_FILTER_ENABLED: bool = True
    NEWS_PAUSE_MINUTES: int = 30        # pause 30min before/after major news

    # Dashboard
    PORT: int = 8000
    DASHBOARD_SECRET_KEY: str = "change_me"

    # App
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    @property
    def is_paper(self) -> bool:
        return self.TRADING_MODE == "paper"

    @property
    def database_url_async(self) -> str:
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("sqlite://") and "+aiosqlite" not in url:
            url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        return url

    @property
    def confirmation_timeframe_list(self):
        return [tf.strip() for tf in self.CONFIRMATION_TIMEFRAMES.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
