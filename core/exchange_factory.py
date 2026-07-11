"""
Exchange Factory
Returns the correct exchange implementation based on TRADING_MODE setting.
This is the ONLY place that should care about paper vs live —
the rest of the bot just uses the ExchangeInterface.
"""
from loguru import logger
from core.exchange_interface import ExchangeInterface
from core.live_exchange import LiveExchange
from core.paper_exchange import PaperExchange
from config.settings import settings


def create_exchange() -> ExchangeInterface:
    """Factory function: builds the exchange engine matching TRADING_MODE"""
    if settings.is_paper:
        logger.info("📝 Mode: PAPER TRADING (simulated, virtual balance, real prices)")
        return PaperExchange(starting_balance=settings.PAPER_STARTING_BALANCE)
    else:
        logger.warning("💰 Mode: LIVE TRADING (REAL MONEY on XT.com)")
        return LiveExchange()
