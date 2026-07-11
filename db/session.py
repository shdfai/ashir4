"""
Database Session Manager
Handles async engine/session creation and provides repository functions
for trades, equity snapshots, and system events.
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, func, desc
from contextlib import asynccontextmanager
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from loguru import logger

from db.models import Base, Trade, EquitySnapshot, AITrainingLog, SystemEvent
from config.settings import settings

engine = create_async_engine(settings.database_url_async, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db():
    """Create all tables if they don't exist"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables initialized")


@asynccontextmanager
async def get_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ─── Trade Repository ─────────────────────────────────────────────────────

async def create_trade(**kwargs) -> Trade:
    async with get_session() as session:
        trade = Trade(**kwargs)
        session.add(trade)
        await session.flush()
        await session.refresh(trade)
        return trade


async def close_trade(trade_id: int, exit_price: float, pnl_usdt: float,
                       pnl_pct: float, exit_reason: str) -> Optional[Trade]:
    async with get_session() as session:
        result = await session.execute(select(Trade).where(Trade.id == trade_id))
        trade = result.scalar_one_or_none()
        if trade:
            trade.exit_price = exit_price
            trade.pnl_usdt = pnl_usdt
            trade.pnl_pct = pnl_pct
            trade.exit_reason = exit_reason
            trade.status = "closed"
            trade.closed_at = datetime.utcnow()
            await session.flush()
            await session.refresh(trade)
        return trade


async def get_open_trades(mode: str = None) -> List[Trade]:
    async with get_session() as session:
        query = select(Trade).where(Trade.status == "open")
        if mode:
            query = query.where(Trade.mode == mode)
        result = await session.execute(query)
        return list(result.scalars().all())


async def get_trade_history(mode: str = None, limit: int = 100) -> List[Trade]:
    async with get_session() as session:
        query = select(Trade).where(Trade.status == "closed").order_by(desc(Trade.closed_at)).limit(limit)
        if mode:
            query = query.where(Trade.mode == mode)
        result = await session.execute(query)
        return list(result.scalars().all())


async def get_trades_since(since: datetime, mode: str = None) -> List[Trade]:
    async with get_session() as session:
        query = select(Trade).where(Trade.opened_at >= since)
        if mode:
            query = query.where(Trade.mode == mode)
        result = await session.execute(query)
        return list(result.scalars().all())


# ─── Equity Repository ────────────────────────────────────────────────────

async def record_equity_snapshot(mode: str, balance: float, equity: float, open_positions: int):
    async with get_session() as session:
        snap = EquitySnapshot(
            mode=mode, balance_usdt=balance, equity_usdt=equity, open_positions=open_positions
        )
        session.add(snap)


async def get_equity_curve(mode: str = None, limit: int = 500) -> List[EquitySnapshot]:
    async with get_session() as session:
        query = select(EquitySnapshot).order_by(EquitySnapshot.timestamp).limit(limit)
        if mode:
            query = query.where(EquitySnapshot.mode == mode)
        result = await session.execute(query)
        return list(result.scalars().all())


# ─── AI Training Log ──────────────────────────────────────────────────────

async def log_ai_training(symbol: str, rf_acc: float, gb_acc: float, ensemble_acc: float, samples: int):
    async with get_session() as session:
        log = AITrainingLog(
            symbol=symbol, rf_accuracy=rf_acc, gb_accuracy=gb_acc,
            ensemble_accuracy=ensemble_acc, samples=samples
        )
        session.add(log)


# ─── System Events ─────────────────────────────────────────────────────────

async def log_system_event(event_type: str, message: str):
    async with get_session() as session:
        event = SystemEvent(event_type=event_type, message=message)
        session.add(event)
    logger.info(f"[EVENT] {event_type}: {message}")


async def get_recent_events(limit: int = 50) -> List[SystemEvent]:
    async with get_session() as session:
        query = select(SystemEvent).order_by(desc(SystemEvent.timestamp)).limit(limit)
        result = await session.execute(query)
        return list(result.scalars().all())


# ─── Performance Metrics ──────────────────────────────────────────────────

async def calculate_performance_metrics(mode: str = None, days: int = 30) -> Dict:
    """
    Calculate comprehensive performance metrics:
    Win Rate, Sharpe Ratio, Max Drawdown, Profit Factor, Best/Worst Trade, etc.
    """
    since = datetime.utcnow() - timedelta(days=days)
    trades = await get_trades_since(since, mode)
    closed = [t for t in trades if t.status == "closed" and t.pnl_usdt is not None]

    if not closed:
        return _empty_metrics()

    pnls = [t.pnl_usdt for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    win_rate = len(wins) / len(closed) * 100 if closed else 0
    total_pnl = sum(pnls)
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf') if wins else 0

    best_trade = max(pnls) if pnls else 0
    worst_trade = min(pnls) if pnls else 0

    # Sharpe Ratio (simplified, using per-trade returns)
    returns = [t.pnl_pct for t in closed if t.pnl_pct is not None]
    sharpe = _calculate_sharpe(returns)

    # Max Drawdown from equity curve
    equity_curve = await get_equity_curve(mode, limit=2000)
    max_dd, max_dd_pct = _calculate_max_drawdown(equity_curve)

    return {
        "total_trades": len(closed),
        "win_rate": round(win_rate, 1),
        "total_pnl_usdt": round(total_pnl, 2),
        "avg_win_usdt": round(avg_win, 2),
        "avg_loss_usdt": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else None,
        "best_trade_usdt": round(best_trade, 2),
        "worst_trade_usdt": round(worst_trade, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_usdt": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "wins": len(wins),
        "losses": len(losses),
        "period_days": days,
    }


def _empty_metrics() -> Dict:
    return {
        "total_trades": 0, "win_rate": 0, "total_pnl_usdt": 0,
        "avg_win_usdt": 0, "avg_loss_usdt": 0, "profit_factor": None,
        "best_trade_usdt": 0, "worst_trade_usdt": 0, "sharpe_ratio": 0,
        "max_drawdown_usdt": 0, "max_drawdown_pct": 0, "wins": 0, "losses": 0,
        "period_days": 30,
    }


def _calculate_sharpe(returns: List[float], risk_free_rate: float = 0.0) -> float:
    """Simplified Sharpe ratio from per-trade % returns"""
    if not returns or len(returns) < 2:
        return 0.0
    import statistics
    mean_return = statistics.mean(returns)
    std_return = statistics.stdev(returns)
    if std_return == 0:
        return 0.0
    return (mean_return - risk_free_rate) / std_return


def _calculate_max_drawdown(equity_curve: List[EquitySnapshot]) -> tuple:
    """Calculate max drawdown in USDT and percentage from equity curve"""
    if not equity_curve:
        return 0.0, 0.0

    peak = equity_curve[0].equity_usdt
    max_dd = 0.0
    max_dd_pct = 0.0

    for snap in equity_curve:
        if snap.equity_usdt > peak:
            peak = snap.equity_usdt
        dd = peak - snap.equity_usdt
        dd_pct = (dd / peak * 100) if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct

    return max_dd, max_dd_pct
