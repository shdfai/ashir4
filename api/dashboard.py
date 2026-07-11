"""
FastAPI Dashboard Backend
REST API + WebSocket for the professional trading dashboard.
Serves: live status, balance, positions, full trade history,
performance metrics (Win Rate, Sharpe, Max Drawdown, Profit Factor),
and equity curve data for charting.
"""
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from typing import List
import asyncio
from datetime import datetime
from loguru import logger

from db.session import (
    get_trade_history, get_open_trades, get_equity_curve,
    calculate_performance_metrics, get_recent_events,
)
from config.settings import settings

app = FastAPI(title="XT Trading Bot Dashboard", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

bot_instance = None  # injected from main.py
active_connections: List[WebSocket] = []


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            data = await _build_live_payload()
            await websocket.send_json(data)
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        active_connections.remove(websocket)


async def _build_live_payload() -> dict:
    if not bot_instance:
        return {"status": "offline"}
    try:
        bal = await bot_instance.exchange.get_balance()
        stats = bot_instance.risk.get_stats()
        positions = await bot_instance.exchange.get_open_positions()
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "mode": settings.TRADING_MODE,
            "balance": bal,
            "stats": stats,
            "positions": positions,
            "symbols": bot_instance.symbols,
        }
    except Exception as e:
        return {"error": str(e)}


# ─── REST Endpoints ───────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    return await _build_live_payload()


@app.get("/api/positions")
async def api_positions():
    if not bot_instance:
        return []
    return await bot_instance.exchange.get_open_positions()


@app.get("/api/balance")
async def api_balance():
    if not bot_instance:
        return {}
    return await bot_instance.exchange.get_balance()


@app.get("/api/history")
async def api_history(limit: int = 100):
    trades = await get_trade_history(mode=settings.TRADING_MODE, limit=limit)
    return [t.to_dict() for t in trades]


@app.get("/api/open-trades-db")
async def api_open_trades_db():
    trades = await get_open_trades(mode=settings.TRADING_MODE)
    return [t.to_dict() for t in trades]


@app.get("/api/metrics")
async def api_metrics(days: int = 30):
    return await calculate_performance_metrics(mode=settings.TRADING_MODE, days=days)


@app.get("/api/equity-curve")
async def api_equity_curve(limit: int = 500):
    curve = await get_equity_curve(mode=settings.TRADING_MODE, limit=limit)
    return [c.to_dict() for c in curve]


@app.get("/api/events")
async def api_events(limit: int = 50):
    events = await get_recent_events(limit=limit)
    return [e.to_dict() for e in events]


@app.post("/api/halt")
async def api_halt():
    if not bot_instance:
        raise HTTPException(400, "Bot not running")
    bot_instance.risk._halt_trading("Halted via dashboard")
    return {"message": "Trading halted"}


@app.post("/api/resume")
async def api_resume():
    if not bot_instance:
        raise HTTPException(400, "Bot not running")
    bot_instance.risk.resume_trading()
    return {"message": "Trading resumed"}


@app.get("/api/mode")
async def api_mode():
    return {
        "mode": settings.TRADING_MODE,
        "is_paper": settings.is_paper,
        "paper_starting_balance": settings.PAPER_STARTING_BALANCE,
    }


# Dashboard HTML is served from a separate static file (see api/dashboard_html.py)
from api.dashboard_html import DASHBOARD_HTML

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML
