"""
Web Server (aiohttp + WebSocket)

Serves the dashboard UI and streams real-time account state
to the browser via WebSocket.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from aiohttp import web

from src.simulation.account import SimulatedAccount
from src.simulation.engine import TradingEngine
from src.utils.logger import setup_logger

logger = setup_logger("web.server")

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Global state
account: Optional[SimulatedAccount] = None
engine: Optional[TradingEngine] = None
engine_task: Optional[asyncio.Task] = None


def _get_state() -> dict:
    if not account:
        return {"error": "not initialized"}
    state = account.get_state()
    state["engine_running"] = engine.is_running if engine else False
    state["decisions"] = engine.decision_log[:30] if engine else []
    state["scan_count"] = engine._scan_count if engine else 0
    state["server_time"] = datetime.now().isoformat()
    return state


async def index(request: web.Request) -> web.Response:
    html_path = TEMPLATES_DIR / "index.html"
    return web.Response(
        text=html_path.read_text(encoding="utf-8"),
        content_type="text/html",
    )


async def api_start(request: web.Request) -> web.Response:
    global engine_task
    if engine and not engine.is_running:
        engine_task = asyncio.create_task(engine.start())
        return web.json_response({"status": "started"})
    return web.json_response({"status": "already_running"})


async def api_stop(request: web.Request) -> web.Response:
    if engine and engine.is_running:
        engine.stop()
        return web.json_response({"status": "stopped"})
    return web.json_response({"status": "not_running"})


async def api_state(request: web.Request) -> web.Response:
    return web.json_response(
        _get_state(),
        dumps=lambda o: json.dumps(o, default=str),
    )


async def _push_state(ws: web.WebSocketResponse):
    """Background task that pushes account state every 2 seconds."""
    try:
        while not ws.closed:
            await asyncio.sleep(2)
            if ws.closed:
                break
            try:
                await ws.send_str(json.dumps(_get_state(), default=str))
            except (ConnectionResetError, ConnectionError):
                break
    except asyncio.CancelledError:
        pass


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    logger.info("Client connected")

    # Send initial state
    try:
        await ws.send_str(json.dumps(_get_state(), default=str))
    except (ConnectionResetError, ConnectionError):
        return ws

    # Start background push task
    push_task = asyncio.create_task(_push_state(ws))

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                cmd = json.loads(msg.data)
                if cmd.get("action") == "start":
                    await api_start(request)
                elif cmd.get("action") == "stop":
                    await api_stop(request)
            elif msg.type == web.WSMsgType.ERROR:
                break
    except Exception as e:
        logger.debug("WebSocket error: %s", e)
    finally:
        push_task.cancel()
        logger.info("Client disconnected")

    return ws


def create_app(starting_balance: float = 1000.0) -> web.Application:
    global account, engine
    account = SimulatedAccount(starting_balance=starting_balance)
    engine = TradingEngine(account=account)

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_post("/api/start", api_start)
    app.router.add_post("/api/stop", api_stop)
    app.router.add_get("/api/state", api_state)
    app.router.add_get("/ws", websocket_handler)
    return app


def run_server(starting_balance: float = 1000.0, port: int = 8899):
    app = create_app(starting_balance)
    web.run_app(app, host="127.0.0.1", port=port, print=None)
