"""
Database Models
SQLAlchemy ORM models for trade history, equity snapshots, and AI training logs.
"""
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, Text, func
)
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class Trade(Base):
    """A single completed or open trade record"""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    direction = Column(String(8), nullable=False)        # long | short
    mode = Column(String(8), nullable=False, default="paper")  # paper | live

    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)

    quantity = Column(Float, nullable=False)
    position_value_usdt = Column(Float, nullable=False)
    leverage = Column(Integer, nullable=False, default=10)

    pnl_usdt = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    fees_usdt = Column(Float, nullable=True, default=0.0)

    status = Column(String(12), nullable=False, default="open")  # open | closed | cancelled
    exit_reason = Column(String(64), nullable=True)              # tp_hit | sl_hit | ai_exit | manual

    strategy_tag = Column(String(64), nullable=True)   # e.g. "ai+scalp"
    ai_confidence = Column(Float, nullable=True)
    market_regime = Column(String(16), nullable=True)  # trending | ranging | volatile

    opened_at = Column(DateTime, default=datetime.utcnow, index=True)
    closed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "direction": self.direction,
            "mode": self.mode,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "quantity": self.quantity,
            "position_value_usdt": self.position_value_usdt,
            "leverage": self.leverage,
            "pnl_usdt": self.pnl_usdt,
            "pnl_pct": self.pnl_pct,
            "fees_usdt": self.fees_usdt,
            "status": self.status,
            "exit_reason": self.exit_reason,
            "strategy_tag": self.strategy_tag,
            "ai_confidence": self.ai_confidence,
            "market_regime": self.market_regime,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }


class EquitySnapshot(Base):
    """Periodic snapshot of account equity, used for equity curve & drawdown calc"""
    __tablename__ = "equity_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mode = Column(String(8), nullable=False, default="paper")
    balance_usdt = Column(Float, nullable=False)
    equity_usdt = Column(Float, nullable=False)  # balance + unrealized PnL
    open_positions = Column(Integer, default=0)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "mode": self.mode,
            "balance_usdt": self.balance_usdt,
            "equity_usdt": self.equity_usdt,
            "open_positions": self.open_positions,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class AITrainingLog(Base):
    """Log of AI model retraining events"""
    __tablename__ = "ai_training_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    rf_accuracy = Column(Float, nullable=True)
    gb_accuracy = Column(Float, nullable=True)
    ensemble_accuracy = Column(Float, nullable=True)
    samples = Column(Integer, nullable=True)
    trained_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "rf_accuracy": self.rf_accuracy,
            "gb_accuracy": self.gb_accuracy,
            "ensemble_accuracy": self.ensemble_accuracy,
            "samples": self.samples,
            "trained_at": self.trained_at.isoformat() if self.trained_at else None,
        }


class SystemEvent(Base):
    """Log of important system events (halts, errors, mode switches)"""
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(32), nullable=False)  # halt | resume | error | mode_switch | startup
    message = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "event_type": self.event_type,
            "message": self.message,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
