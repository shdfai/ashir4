"""Main entrypoint v3"""
import asyncio
import uvicorn
from loguru import logger
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.bot import TradingBotV3 as TradingBot
from api.dashboard import app as dashboard_app
import api.dashboard as dashboard_module
from config.settings import settings

logger.remove()
logger.add(sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level=settings.LOG_LEVEL)
os.makedirs("logs", exist_ok=True)
os.makedirs("models", exist_ok=True)
logger.add("logs/bot.log", rotation="1 day", retention="30 days", level="DEBUG")


async def main():
    bot = TradingBot()
    dashboard_module.bot_instance = bot
    bot.telegram.bot_ref = bot

    port = int(os.environ.get("PORT", settings.PORT))
    config = uvicorn.Config(app=dashboard_app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)

    logger.info(f"🌐 Dashboard on port {port} | Mode: {settings.TRADING_MODE.upper()}")
    await asyncio.gather(server.serve(), bot.start())


if __name__ == "__main__":
    asyncio.run(main())
