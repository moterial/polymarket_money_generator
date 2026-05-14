"""
Auto-Trading Decision Engine

Takes scan results and automatically makes trading decisions
that affect the simulated $1,000 account.

Decision logic:
1. For each arbitrage opportunity found, evaluate if we should trade
2. Size positions based on Kelly criterion / edge strength
3. Monitor existing positions and close when edge disappears
4. Enforce risk limits (max position size, max drawdown, diversification)
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import Optional

from src.simulation.account import OrderSide, SimulatedAccount
from src.scanner.market_scanner import MarketScanner, ScanResult
from src.utils.data_models import ArbitrageOpportunity
from src.utils.logger import setup_logger

logger = setup_logger("simulation.engine")


class TradingEngine:
    """
    Automated decision engine that runs the simulated account.

    Continuously scans markets and executes trades when opportunities
    meet the criteria. Every decision impacts the $1,000 account.
    """

    def __init__(
        self,
        account: SimulatedAccount,
        max_position_pct: float = 10.0,    # max % of equity per trade
        max_total_exposure_pct: float = 60.0,  # max % of equity in positions
        min_edge_to_trade: float = 1.0,    # minimum edge % to enter
        min_confidence: float = 0.50,      # minimum confidence to enter
        max_open_positions: int = 10,
    ):
        self.account = account
        self.scanner = MarketScanner()
        self.max_position_pct = max_position_pct
        self.max_total_exposure_pct = max_total_exposure_pct
        self.min_edge_to_trade = min_edge_to_trade
        self.min_confidence = min_confidence
        self.max_open_positions = max_open_positions

        self._running = False
        self._scan_count = 0
        self._last_result: Optional[ScanResult] = None
        self._decision_log: list[dict] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_result(self) -> Optional[ScanResult]:
        return self._last_result

    @property
    def decision_log(self) -> list[dict]:
        return list(reversed(self._decision_log[-100:]))

    async def start(self):
        """Start the continuous trading loop."""
        self._running = True
        logger.info("Trading engine started with $%.2f", self.account.starting_balance)

        try:
            while self._running:
                await self._run_cycle()
                # Wait between scans (30-60s with jitter to avoid pattern detection)
                wait = 30 + random.uniform(0, 15)
                await asyncio.sleep(wait)
        except asyncio.CancelledError:
            logger.info("Trading engine stopped")
        finally:
            self._running = False
            await self.scanner.client.close()

    def stop(self):
        """Signal the engine to stop."""
        self._running = False
        logger.info("Trading engine stop requested")

    async def _run_cycle(self):
        """One complete scan → decide → trade cycle."""
        self._scan_count += 1
        cycle_id = self._scan_count

        try:
            # 1. Scan markets
            self._log_decision(cycle_id, "SCAN", "Starting market scan...")
            result = await self.scanner.scan_once()
            self._last_result = result
            self._log_decision(
                cycle_id, "SCAN_DONE",
                f"Found {len(result.opportunities)} opportunities "
                f"across {result.markets_scanned} markets "
                f"in {result.scan_duration_ms:.0f}ms",
            )

            # 2. Update existing position prices
            await self._update_positions(result)

            # 3. Check if we should close any positions
            await self._check_exits(cycle_id)

            # 4. Evaluate new opportunities (max 3 new trades per cycle)
            trades_this_cycle = 0
            for opp in result.opportunities:
                if not self._running:
                    break
                if trades_this_cycle >= 3:
                    break
                traded = await self._evaluate_opportunity(cycle_id, opp)
                if traded:
                    trades_this_cycle += 1

        except Exception as e:
            logger.error("Cycle %d error: %s", cycle_id, e)
            self._log_decision(cycle_id, "ERROR", str(e))

    async def _evaluate_opportunity(self, cycle_id: int, opp: ArbitrageOpportunity) -> bool:
        """Decide whether to trade an opportunity. Returns True if traded."""
        # Check basic filters
        if opp.edge_pct < self.min_edge_to_trade:
            return False

        if opp.confidence < self.min_confidence:
            self._log_decision(
                cycle_id, "SKIP",
                f"Low confidence ({opp.confidence:.0%}): {opp.description[:60]}",
            )
            return False

        # Check position limits
        n_positions = len(self.account.positions)
        if n_positions >= self.max_open_positions:
            return False

        # Check total exposure
        total_exposure = sum(p.market_value for p in self.account.positions.values())
        if total_exposure / self.account.equity * 100 > self.max_total_exposure_pct:
            return False

        # Size the position using fractional Kelly
        position_size_usd = self._kelly_size(opp)
        if position_size_usd < 1.0:
            return False

        # Check we don't already have a position in any of this opportunity's markets
        for leg in opp.legs:
            market_id = leg.get("market", "")
            if not market_id:
                continue
            for pos_key in self.account.positions:
                if market_id in pos_key:
                    return False

        # Only execute BUY legs (we open positions, not naked sells)
        buy_legs = [leg for leg in opp.legs
                    if leg.get("side", "").startswith("BUY") and 0 < leg.get("price", 0) < 1]
        if not buy_legs:
            return False

        # Fetch CLOB midpoints for accurate entry prices (Gamma snapshots are stale)
        market_map: dict[str, "Market"] = {}
        for event in self.scanner._last_events:
            for market in event.markets:
                market_map[market.condition_id] = market

        resolved_legs: list[dict] = []
        for leg in buy_legs:
            cid = leg.get("market", "")
            side_str = leg.get("side", "BUY_YES")
            token_side = "YES" if "YES" in side_str else "NO"
            market = market_map.get(cid)
            if not market:
                continue
            # Find the token_id for this side
            token_id = ""
            for tok in market.tokens:
                if tok.outcome.upper() == token_side:
                    token_id = tok.token_id
                    break
            if not token_id:
                continue
            # Fetch live midpoint
            try:
                mid = await self.scanner.client.get_midpoint(token_id)
                if 0 < mid < 1:
                    resolved_legs.append({**leg, "price": mid})
                else:
                    resolved_legs.append(leg)  # fallback to Gamma price
            except Exception:
                resolved_legs.append(leg)  # fallback to Gamma price

        if not resolved_legs:
            return False

        # EXECUTE!
        self._log_decision(
            cycle_id, "TRADE",
            f"Entering {opp.opportunity_type} trade: {opp.edge_pct:.2f}% edge, "
            f"${position_size_usd:.2f} size | {opp.description[:60]}",
        )

        for leg in resolved_legs:
            price = leg["price"]
            side_str = leg.get("side", "BUY_YES")
            try:
                side = OrderSide(side_str)
            except ValueError:
                side = OrderSide.BUY_YES

            contracts = position_size_usd / price / max(len(resolved_legs), 1)
            question = leg.get("question", opp.description[:60])
            market_id = leg.get("market", "unknown")

            order = self.account.place_order(
                market_id=market_id,
                market_question=question,
                side=side,
                price=price,
                size=contracts,
                reason=f"[{opp.opportunity_type}] {opp.edge_pct:.1f}% edge, conf={opp.confidence:.0%}",
            )

            self._log_decision(
                cycle_id, f"ORDER_{order.status.value}",
                f"{side.value} {contracts:.1f} contracts @ ${price:.4f} = ${order.cost:.2f} "
                f"| {question[:50]}",
            )

        return True

    async def _check_exits(self, cycle_id: int):
        """Check if any existing positions should be closed."""
        positions_to_close: list[str] = []

        for pos_key, pos in list(self.account.positions.items()):
            # Close if unrealized P&L exceeds target (take profit)
            if pos.unrealized_pnl > 0 and pos.unrealized_pnl / pos.cost_basis > 0.15:
                self._log_decision(
                    cycle_id, "TAKE_PROFIT",
                    f"Closing {pos.market_question[:40]} for +${pos.unrealized_pnl:.2f} "
                    f"(+{pos.unrealized_pnl/pos.cost_basis*100:.1f}%)",
                )
                positions_to_close.append(pos_key)

            # Close if stop-loss triggered
            elif pos.unrealized_pnl < 0 and abs(pos.unrealized_pnl) / pos.cost_basis > 0.20:
                self._log_decision(
                    cycle_id, "STOP_LOSS",
                    f"Closing {pos.market_question[:40]} for -${abs(pos.unrealized_pnl):.2f} "
                    f"({pos.unrealized_pnl/pos.cost_basis*100:.1f}%)",
                )
                positions_to_close.append(pos_key)

        for pos_key in positions_to_close:
            if pos_key in self.account.positions:
                pos = self.account.positions[pos_key]
                self.account.close_position(pos_key, pos.current_price)

    async def _update_positions(self, result: ScanResult):
        """Update position prices from CLOB midpoints (real-time orderbook)."""
        if not self.account.positions:
            return

        # Build condition_id → Market lookup from latest scan
        market_map: dict[str, "Market"] = {}
        for event in self.scanner._last_events:
            for market in event.markets:
                market_map[market.condition_id] = market

        # For each position, find the token_id we need to price
        # pos_key format: {condition_id}_{YES/NO}
        token_to_pos: dict[str, str] = {}  # token_id → pos_key
        for pos_key, pos in list(self.account.positions.items()):
            cid = pos.market_id
            side = pos.side  # "YES" or "NO"
            market = market_map.get(cid)
            if not market:
                continue
            for tok in market.tokens:
                if tok.outcome.upper() == side and tok.token_id:
                    token_to_pos[tok.token_id] = pos_key
                    break

        if not token_to_pos:
            return

        # Fetch CLOB midpoints for all position tokens
        price_map: dict[str, float] = {}
        tasks = [self.scanner.client.get_midpoint(tid) for tid in token_to_pos]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for tid, mid in zip(token_to_pos, results):
            if isinstance(mid, float) and 0 < mid < 1:
                pos_key = token_to_pos[tid]
                price_map[pos_key] = mid

        if price_map:
            self.account.update_position_prices(price_map)

    def _kelly_size(self, opp: ArbitrageOpportunity) -> float:
        """
        Fractional Kelly sizing.

        For prediction market trades, we estimate position size based on
        the opportunity's edge and confidence. Uses quarter-Kelly for safety.
        """
        edge = opp.edge_pct / 100.0  # e.g., 3% → 0.03
        if edge <= 0:
            return 0

        # For stat trades, use a simple edge-based sizing
        # Fraction of bankroll = edge * confidence (capped)
        fraction = edge * opp.confidence
        fraction = max(0.01, min(fraction, 0.15))  # 1% to 15%

        # Quarter-Kelly for safety
        fraction *= 0.25

        # Cap at max position %
        max_usd = self.account.equity * self.max_position_pct / 100
        position_usd = self.account.equity * fraction

        return min(position_usd, max_usd)

    def _log_decision(self, cycle_id: int, action: str, message: str):
        """Log a decision for the UI."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "cycle": cycle_id,
            "action": action,
            "message": message,
        }
        self._decision_log.append(entry)
        # Keep manageable size
        if len(self._decision_log) > 500:
            self._decision_log = self._decision_log[-300:]
        logger.info("[Cycle %d] %s: %s", cycle_id, action, message)
