"""
Polymarket CLOB API Client

Handles all interactions with the Polymarket Central Limit Order Book API.
Endpoints: markets, events, orderbooks, prices, trades.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from config.settings import settings
from src.utils.data_models import (
    Event, Market, OrderBook, OrderBookLevel, PriceHistory, Token,
)
from src.utils.logger import setup_logger

logger = setup_logger("api.clob")

CLOB_BASE = settings.api.clob_url
GAMMA_BASE = settings.api.gamma_url

# Rate limit: generous defaults
_SEM = asyncio.Semaphore(10)


def _parse_tokens(m: dict) -> list[Token]:
    """Parse tokens from a Gamma API market dict.

    The Gamma API returns parallel arrays:
      outcomes: ["Yes", "No"]
      outcomePrices: ["0.55", "0.45"]
      clobTokenIds: ["abc...", "def..."]
    Older/alternative format uses a nested 'tokens' list.
    """
    # Try parallel-array format first (current Gamma API)
    outcomes = m.get("outcomes")
    if isinstance(outcomes, str):
        try:
            import json as _json
            outcomes = _json.loads(outcomes)
        except Exception:
            outcomes = None
    prices_raw = m.get("outcomePrices")
    if isinstance(prices_raw, str):
        try:
            import json as _json
            prices_raw = _json.loads(prices_raw)
        except Exception:
            prices_raw = None
    token_ids_raw = m.get("clobTokenIds")
    if isinstance(token_ids_raw, str):
        try:
            import json as _json
            token_ids_raw = _json.loads(token_ids_raw)
        except Exception:
            token_ids_raw = None

    if outcomes and isinstance(outcomes, list):
        prices = prices_raw or []
        token_ids = token_ids_raw or []
        tokens: list[Token] = []
        for i, outcome in enumerate(outcomes):
            price = 0.0
            if i < len(prices):
                try:
                    price = float(prices[i])
                except (ValueError, TypeError):
                    pass
            tid = ""
            if i < len(token_ids):
                tid = str(token_ids[i])
            tokens.append(Token(token_id=tid, outcome=outcome, price=price))
        return tokens

    # Fallback: nested tokens array
    tokens = []
    for t in m.get("tokens", []):
        tokens.append(Token(
            token_id=t.get("token_id", ""),
            outcome=t.get("outcome", ""),
            price=float(t.get("price", 0)),
        ))
    return tokens


class PolymarketClient:
    """Async client for Polymarket CLOB + Gamma APIs."""

    def __init__(self) -> None:
        self._http: Optional[httpx.AsyncClient] = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    # ── Gamma API (metadata) ────────────────────────────────────────

    async def get_events(
        self,
        limit: int = 100,
        active: bool = True,
        closed: bool = False,
        tag: Optional[str] = None,
        after_cursor: Optional[str] = None,
    ) -> tuple[list[Event], Optional[str]]:
        """Fetch events from Gamma API with keyset pagination."""
        client = await self._client()
        params: dict[str, Any] = {
            "limit": limit,
            "active": active,
            "closed": closed,
        }
        if tag:
            params["tag"] = tag
        if after_cursor:
            params["after_cursor"] = after_cursor

        async with _SEM:
            resp = await client.get(f"{GAMMA_BASE}/events", params=params)
            resp.raise_for_status()

        data = resp.json()
        events: list[Event] = []
        for ev in data if isinstance(data, list) else data.get("data", []):
            markets = []
            for m in ev.get("markets", []):
                tokens = _parse_tokens(m)
                markets.append(Market(
                    condition_id=m.get("conditionId", m.get("condition_id", "")),
                    question=m.get("question", ""),
                    slug=m.get("market_slug", m.get("slug", "")),
                    tokens=tokens,
                    end_date=m.get("end_date_iso"),
                    active=m.get("active", True),
                    closed=m.get("closed", False),
                    volume=float(m.get("volume", 0) or 0),
                    liquidity=float(m.get("liquidity", 0) or 0),
                    neg_risk=m.get("neg_risk", False),
                    event_id=ev.get("id", ""),
                    tags=[t.get("slug", "") for t in ev.get("tags", [])],
                ))
            events.append(Event(
                event_id=ev.get("id", ""),
                title=ev.get("title", ""),
                slug=ev.get("slug", ""),
                markets=markets,
                tags=[t.get("slug", "") for t in ev.get("tags", [])],
            ))

        next_cursor = None
        if isinstance(data, dict):
            next_cursor = data.get("next_cursor")

        return events, next_cursor

    async def get_all_active_events(self, max_pages: int = 10) -> list[Event]:
        """Paginate through all active events."""
        all_events: list[Event] = []
        cursor: Optional[str] = None
        for _ in range(max_pages):
            events, cursor = await self.get_events(limit=100, after_cursor=cursor)
            all_events.extend(events)
            if not cursor or not events:
                break
        logger.info("Fetched %d active events", len(all_events))
        return all_events

    async def get_markets(
        self,
        limit: int = 100,
        after_cursor: Optional[str] = None,
    ) -> tuple[list[Market], Optional[str]]:
        """Fetch markets from Gamma API."""
        client = await self._client()
        params: dict[str, Any] = {"limit": limit, "active": True}
        if after_cursor:
            params["after_cursor"] = after_cursor

        async with _SEM:
            resp = await client.get(f"{GAMMA_BASE}/markets", params=params)
            resp.raise_for_status()

        data = resp.json()
        markets: list[Market] = []
        items = data if isinstance(data, list) else data.get("data", [])
        for m in items:
            tokens = _parse_tokens(m)
            markets.append(Market(
                condition_id=m.get("conditionId", m.get("condition_id", "")),
                question=m.get("question", ""),
                slug=m.get("market_slug", m.get("slug", "")),
                tokens=tokens,
                end_date=m.get("end_date_iso"),
                active=m.get("active", True),
                closed=m.get("closed", False),
                volume=float(m.get("volume", 0) or 0),
                liquidity=float(m.get("liquidity", 0) or 0),
                neg_risk=m.get("neg_risk", False),
                event_id=m.get("event_id", ""),
                tags=[],
            ))

        next_cursor = None
        if isinstance(data, dict):
            next_cursor = data.get("next_cursor")

        return markets, next_cursor

    async def search_markets(self, query: str) -> list[Market]:
        """Search markets by text query."""
        client = await self._client()
        async with _SEM:
            resp = await client.get(
                f"{GAMMA_BASE}/search",
                params={"query": query, "limit": 50},
            )
            resp.raise_for_status()

        data = resp.json()
        markets: list[Market] = []
        for m in data.get("markets", data if isinstance(data, list) else []):
            tokens = _parse_tokens(m)
            markets.append(Market(
                condition_id=m.get("conditionId", m.get("condition_id", "")),
                question=m.get("question", ""),
                slug=m.get("market_slug", m.get("slug", "")),
                tokens=tokens,
                volume=float(m.get("volume", 0) or 0),
                liquidity=float(m.get("liquidity", 0) or 0),
                neg_risk=m.get("neg_risk", False),
            ))
        return markets

    # ── CLOB API (orderbook / prices) ───────────────────────────────

    async def get_orderbook(self, token_id: str) -> OrderBook:
        """Fetch full orderbook for a token."""
        client = await self._client()
        async with _SEM:
            resp = await client.get(
                f"{CLOB_BASE}/book",
                params={"token_id": token_id},
            )
            resp.raise_for_status()

        data = resp.json()
        bids = [OrderBookLevel(float(b["price"]), float(b["size"]))
                for b in data.get("bids", [])]
        asks = [OrderBookLevel(float(a["price"]), float(a["size"]))
                for a in data.get("asks", [])]
        # Sort: bids descending, asks ascending
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)

        return OrderBook(token_id=token_id, bids=bids, asks=asks)

    async def get_midpoint(self, token_id: str) -> float:
        """Get midpoint price for a token."""
        client = await self._client()
        async with _SEM:
            resp = await client.get(
                f"{CLOB_BASE}/midpoint",
                params={"token_id": token_id},
            )
            resp.raise_for_status()
        data = resp.json()
        return float(data.get("mid", 0.5))

    async def get_midpoints_batch(self, token_ids: list[str]) -> dict[str, float]:
        """Batch fetch midpoints for multiple tokens."""
        client = await self._client()
        # Use request body variant for batch
        async with _SEM:
            resp = await client.post(
                f"{CLOB_BASE}/midpoints",
                json=token_ids,
            )
            resp.raise_for_status()
        data = resp.json()
        return {k: float(v) for k, v in data.items()}

    async def get_spread(self, token_id: str) -> dict[str, float]:
        """Get spread for a token."""
        client = await self._client()
        async with _SEM:
            resp = await client.get(
                f"{CLOB_BASE}/spread",
                params={"token_id": token_id},
            )
            resp.raise_for_status()
        return resp.json()

    async def get_last_trade_price(self, token_id: str) -> float:
        """Get the last traded price for a token."""
        client = await self._client()
        async with _SEM:
            resp = await client.get(
                f"{CLOB_BASE}/last-trade-price",
                params={"token_id": token_id},
            )
            resp.raise_for_status()
        data = resp.json()
        return float(data.get("price", 0.5))

    async def get_price_history(
        self,
        token_id: str,
        fidelity: int = 60,  # minutes per candle
    ) -> PriceHistory:
        """Fetch price history for a token from Gamma."""
        client = await self._client()
        async with _SEM:
            resp = await client.get(
                f"{GAMMA_BASE}/prices-history",
                params={"market": token_id, "fidelity": fidelity},
            )
            resp.raise_for_status()

        data = resp.json()
        from datetime import datetime

        history = PriceHistory(token_id=token_id)
        for point in data.get("history", data if isinstance(data, list) else []):
            ts = point.get("t")
            price = point.get("p")
            if ts is not None and price is not None:
                if isinstance(ts, (int, float)):
                    history.timestamps.append(datetime.fromtimestamp(ts))
                else:
                    history.timestamps.append(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
                history.prices.append(float(price))

        return history

    # ── Batch helpers ───────────────────────────────────────────────

    async def refresh_market_prices(self, markets: list[Market]) -> list[Market]:
        """Refresh prices for markets that don't already have them."""
        token_ids = []
        token_map: dict[str, tuple[Market, Token]] = {}
        for m in markets:
            # Skip markets that already have prices from the Gamma API
            if m.yes_price > 0:
                continue
            for t in m.tokens:
                if t.token_id and t.price <= 0:
                    token_ids.append(t.token_id)
                    token_map[t.token_id] = (m, t)

        if not token_ids:
            return markets

        logger.info("Refreshing prices for %d tokens without prices", len(token_ids))

        # Batch in chunks of 100 — use GET with comma-separated IDs
        for i in range(0, len(token_ids), 100):
            chunk = token_ids[i : i + 100]
            try:
                # Try individual midpoint fetches for small batches
                tasks = [self.get_midpoint(tid) for tid in chunk[:20]]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for tid, res in zip(chunk[:20], results):
                    if isinstance(res, float) and tid in token_map:
                        token_map[tid][1].price = res
            except Exception as e:
                logger.debug("Price refresh chunk failed: %s", e)

        return markets
