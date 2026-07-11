"""
Telegram Bot — Notifications + Remote Status Commands
Per user requirement: notifications ONLY on trade open/close (no spam),
but commands available on-demand for status/balance/positions/stats.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
from loguru import logger
from typing import Optional

from config.settings import settings


class TelegramNotifier:
    def __init__(self):
        self.app: Optional[Application] = None
        self.bot_ref = None  # set to the TradingBot instance after construction

    async def start(self):
        if not settings.TELEGRAM_BOT_TOKEN:
            logger.warning("⚠️ No TELEGRAM_BOT_TOKEN set — Telegram bot disabled")
            return
        try:
            self.app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

            self.app.add_handler(CommandHandler("start", self._cmd_start))
            self.app.add_handler(CommandHandler("status", self._cmd_status))
            self.app.add_handler(CommandHandler("positions", self._cmd_positions))
            self.app.add_handler(CommandHandler("balance", self._cmd_balance))
            self.app.add_handler(CommandHandler("stats", self._cmd_stats))
            self.app.add_handler(CommandHandler("mode", self._cmd_mode))
            self.app.add_handler(CallbackQueryHandler(self._callback_handler))

            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling(drop_pending_updates=True)
            logger.info("✅ Telegram bot started")
        except Exception as e:
            logger.error(f"Telegram start error: {e}")

    async def send_message(self, text: str):
        if not self.app or not settings.TELEGRAM_CHAT_ID:
            return
        try:
            await self.app.bot.send_message(
                chat_id=settings.TELEGRAM_CHAT_ID, text=text, parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Telegram send error: {e}")

    async def send_trade_opened(
        self, symbol: str, direction: str, entry: float, sl: float, tp: float,
        size: float, leverage: int, confidence: float, reason: str, mode: str,
    ):
        emoji = "🟢" if direction == "long" else "🔴"
        mode_tag = "📝 PAPER" if mode == "paper" else "💰 LIVE"
        sl_pct = abs(entry - sl) / entry * 100 if entry else 0
        tp_pct = abs(tp - entry) / entry * 100 if entry else 0
        rr = tp_pct / sl_pct if sl_pct > 0 else 0

        msg = (
            f"{emoji} *TRADE OPENED* [{mode_tag}]\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📌 Symbol: `{symbol}`\n"
            f"📈 Direction: *{direction.upper()}*\n"
            f"💵 Entry: `{entry:.4f}`\n"
            f"🛑 Stop Loss: `{sl:.4f}` (-{sl_pct:.2f}%)\n"
            f"🎯 Take Profit: `{tp:.4f}` (+{tp_pct:.2f}%)\n"
            f"⚖️ R:R: `1:{rr:.1f}`\n"
            f"💼 Size: `${size:.2f}` | Leverage: `{leverage}x`\n"
            f"🎯 Confidence: `{confidence:.0%}`\n"
            f"📝 Reason: _{reason}_"
        )
        await self.send_message(msg)

    async def send_trade_closed(
        self, symbol: str, direction: str, entry: float, exit_price: float,
        pnl: float, pnl_pct: float, reason: str, mode: str,
    ):
        emoji = "✅" if pnl >= 0 else "❌"
        mode_tag = "📝 PAPER" if mode == "paper" else "💰 LIVE"
        msg = (
            f"{emoji} *TRADE CLOSED* [{mode_tag}]\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📌 Symbol: `{symbol}`\n"
            f"📈 Direction: *{direction.upper()}*\n"
            f"💵 Entry → Exit: `{entry:.4f}` → `{exit_price:.4f}`\n"
            f"💰 PnL: `{'+' if pnl >= 0 else ''}{pnl:.2f} USDT` ({pnl_pct:+.2f}%)\n"
            f"📝 Reason: _{reason}_"
        )
        await self.send_message(msg)

    # ─── Commands ────────────────────────────────────────────────────────────

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        await update.message.reply_text(
            "🤖 *XT Trading Bot*\n\n"
            "Commands:\n"
            "/status — bot status\n"
            "/balance — account balance\n"
            "/positions — open positions\n"
            "/stats — trading statistics\n"
            "/mode — current trading mode (paper/live)",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update) or not self.bot_ref:
            return
        stats = self.bot_ref.risk.get_stats()
        status = "🛑 HALTED" if stats["trading_halted"] else "✅ ACTIVE"
        await update.message.reply_text(
            f"⚙️ *Bot Status*\n"
            f"Mode: `{settings.TRADING_MODE.upper()}`\n"
            f"Status: {status}\n"
            f"Open Positions: {stats['open_positions']}\n"
            f"Daily Trades: {stats['daily_trades']}\n"
            f"Daily PnL: ${stats['daily_pnl']:.2f}\n"
            f"Win Rate: {stats['win_rate']}%",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update) or not self.bot_ref:
            return
        bal = await self.bot_ref.exchange.get_balance()
        await update.message.reply_text(
            f"💰 *Balance* ({settings.TRADING_MODE})\n"
            f"Free: `${bal.get('USDT', 0):.2f}`\n"
            f"Total: `${bal.get('total', 0):.2f}`\n"
            f"In Use: `${bal.get('used', 0):.2f}`",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update) or not self.bot_ref:
            return
        positions = await self.bot_ref.exchange.get_open_positions()
        if not positions:
            await update.message.reply_text("📭 No open positions")
            return
        msg = "📊 *Open Positions*\n━━━━━━━━━━━━━━\n"
        for p in positions:
            pnl = p.get("unrealizedPnl", 0)
            emoji = "🟢" if pnl >= 0 else "🔴"
            msg += f"{emoji} `{p.get('symbol')}`  PnL: ${pnl:.2f}\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update) or not self.bot_ref:
            return
        stats = self.bot_ref.risk.get_stats()
        await update.message.reply_text(
            f"📈 *Trading Stats*\n"
            f"Daily PnL: `${stats['daily_pnl']:.2f}`\n"
            f"Trades Today: `{stats['daily_trades']}`\n"
            f"Win Rate: `{stats['win_rate']}%`",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        mode_desc = "📝 Paper Trading (virtual money, real prices)" if settings.is_paper else "💰 LIVE Trading (real money)"
        await update.message.reply_text(f"Current mode: *{mode_desc}*", parse_mode=ParseMode.MARKDOWN)

    async def _callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

    def _is_authorized(self, update: Update) -> bool:
        return str(update.effective_chat.id) == str(settings.TELEGRAM_CHAT_ID)
