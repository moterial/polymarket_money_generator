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
        self._recently_exited: dict[str, float] = {}  # market_id → cooldown_until timestamp

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
        # REJECT settlement-time "arbitrage" — these multi-outcome arbs
        # (lp_optimal, multi_outcome_buy_all_yes/no, overround_value, underround_value)
        # only pay off at market settlement (months away). In the meantime,
        # prices don't move and we just bleed fees on entry/exit.
        # This was THE primary cause of money loss: fake 30-49% "edge"
        # that's unrealizable short-term.
        SETTLEMENT_STRATEGIES = {
            "lp_optimal", "multi_outcome_buy_all_yes", "multi_outcome_buy_all_no",
            "overround_value", "underround_value",
        }
        if opp.opportunity_type in SETTLEMENT_STRATEGIES:
            return False

        # Fee-adjusted edge check: must have positive expected value after fees
        # Polymarket: makers pay 0%, takers ~1-2%. We simulate at midpoint,
        # so ~1% per side is a realistic estimate.
        fee_rate = 0.01
        net_edge = opp.edge_pct - (fee_rate * 2 * 100)  # Round-trip fee in %
        if net_edge < self.min_edge_to_trade:
            return False

        if opp.confidence < self.min_confidence:
            return False

        # Check position limits
        n_positions = len(self.account.positions)
        if n_positions >= self.max_open_positions:
            return False

        # Check total exposure
        total_exposure = sum(p.market_value for p in self.account.positions.values())
        if total_exposure / self.account.equity * 100 > self.max_total_exposure_pct:
            return False

        # Event concentration limit: max 3 positions from same event
        existing_event_positions = 0
        for pos in self.account.positions.values():
            for m in getattr(opp, 'markets', []):
                if m.condition_id == pos.market_id:
                    existing_event_positions += 1
        if existing_event_positions >= 3:
            return False

        # Skip markets that were recently exited (cooldown varies by exit reason)
        import time as _time
        now = _time.time()
        for leg in opp.legs:
            mid = leg.get("market", "")
            if mid in self._recently_exited:
                if now < self._recently_exited[mid]:  # still in cooldown
                    return False
                else:
                    del self._recently_exited[mid]  # expired, clean up

        # Size the position using continuous Kelly
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

        # Verify minimum liquidity on all opportunity markets
        # "liquidity + limits do the real work" — @RohOnChain
        market_map: dict[str, "Market"] = {}
        for event in self.scanner._last_events:
            for market in event.markets:
                market_map[market.condition_id] = market

        for leg in buy_legs:
            cid = leg.get("market", "")
            market = market_map.get(cid)
            if market and market.liquidity < 100:
                return False  # Skip illiquid markets — can't exit reliably

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
            # Fetch live midpoint — REJECT if CLOB has no orderbook (404)
            try:
                mid = await self.scanner.client.get_midpoint(token_id)
                if 0 < mid < 1:
                    resolved_legs.append({**leg, "price": mid, "token_id": token_id})
                else:
                    logger.debug("Skipping leg %s: midpoint %.4f out of range", cid[:16], mid)
                    continue  # Skip — no real orderbook
            except Exception as e:
                logger.debug("Skipping leg %s: CLOB error %s", cid[:16], e)
                continue  # Skip — no CLOB orderbook (404 = settled/delisted)

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
        """Check if any existing positions should be closed.

        Exit rules:
        - Take profit: +30% unrealized return
        - Stop loss: -12% unrealized loss
        - Time exit: close after 24 hours if P&L is flat (< ±3%)
          (Was 4h — but prediction markets are slow; 4h time-exit on
           settlement-time arb just bleeds fees with zero chance of profit)
        - Price stale: if price hasn't changed from entry after 8h,
          CLOB may not be updating → exit to stop holding dead positions
        """
        import time as _time
        positions_to_close: list[tuple[str, str]] = []  # (pos_key, reason)

        for pos_key, pos in list(self.account.positions.items()):
            pnl_pct = pos.unrealized_pnl / pos.cost_basis if pos.cost_basis > 0 else 0
            age_hours = (_time.time() - pos.opened_at) / 3600 if pos.opened_at > 0 else 0

            # Take profit: let winners run to +30%
            if pnl_pct > 0.30:
                self._log_decision(
                    cycle_id, "TAKE_PROFIT",
                    f"Closing {pos.market_question[:40]} for +${pos.unrealized_pnl:.2f} "
                    f"(+{pnl_pct*100:.1f}%)",
                )
                positions_to_close.append((pos_key, "take_profit"))

            # Stop loss: cut losers at -12%
            elif pnl_pct < -0.12:
                self._log_decision(
                    cycle_id, "STOP_LOSS",
                    f"Closing {pos.market_question[:40]} for -${abs(pos.unrealized_pnl):.2f} "
                    f"({pnl_pct*100:.1f}%)",
                )
                positions_to_close.append((pos_key, "stop_loss"))

            # Price stale detection: if current_price == entry_price after 8h,
            # the CLOB is likely not updating this token → exit to free capital
            elif age_hours > 8.0 and abs(pos.current_price - pos.avg_entry_price) < 0.001:
                self._log_decision(
                    cycle_id, "STALE_EXIT",
                    f"Closing {pos.market_question[:40]} — price unchanged from entry "
                    f"after {age_hours:.1f}h (CLOB likely not updating)",
                )
                positions_to_close.append((pos_key, "stale_exit"))

            # Time exit: stale position after 24 hours with negligible P&L
            elif age_hours > 24.0 and abs(pnl_pct) < 0.03:
                self._log_decision(
                    cycle_id, "TIME_EXIT",
                    f"Closing stale {pos.market_question[:40]} after {age_hours:.1f}h "
                    f"({pnl_pct*100:+.1f}%)",
                )
                positions_to_close.append((pos_key, "time_exit"))

        import time as _time
        for pos_key, reason in positions_to_close:
            if pos_key in self.account.positions:
                pos = self.account.positions[pos_key]
                self.account.close_position(pos_key, pos.current_price, reason=reason)
                # Stale exits get 2h cooldown (CLOB broken); others 30min
                cooldown_until = _time.time() + (7200 if reason == "stale_exit" else 1800)
                self._recently_exited[pos.market_id] = cooldown_until

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
        unmatched = 0
        for pos_key, pos in list(self.account.positions.items()):
            cid = pos.market_id
            side = pos.side  # "YES" or "NO"
            market = market_map.get(cid)
            if not market:
                unmatched += 1
                continue
            for tok in market.tokens:
                if tok.outcome.upper() == side and tok.token_id:
                    token_to_pos[tok.token_id] = pos_key
                    break

        if unmatched > 0:
            logger.warning("Price update: %d/%d positions have no matching market in Gamma",
                           unmatched, len(self.account.positions))

        if not token_to_pos:
            return

        # Fetch CLOB midpoints for all position tokens
        price_map: dict[str, float] = {}
        errors = 0
        tasks = [self.scanner.client.get_midpoint(tid) for tid in token_to_pos]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for tid, mid in zip(token_to_pos, results):
            if isinstance(mid, float) and 0 < mid < 1:
                pos_key = token_to_pos[tid]
                price_map[pos_key] = mid
            elif isinstance(mid, Exception):
                errors += 1

        if errors > 0:
            logger.warning("Price update: %d/%d CLOB midpoint fetches failed",
                           errors, len(token_to_pos))

        if price_map:
            self.account.update_position_prices(price_map)
            logger.debug("Price update: updated %d/%d positions",
                         len(price_map), len(self.account.positions))

    def _kelly_size(self, opp: ArbitrageOpportunity) -> float:
        """
        Continuous Kelly sizing: f* = μ/σ²

        For prediction markets, μ = edge (expected return),
        σ² estimated from confidence (lower confidence = higher variance).
        Uses 1/5 Kelly for safety.
        """
        edge = opp.edge_pct / 100.0  # e.g., 3% → 0.03
        if edge <= 0:
            return 0

        # Deduct round-trip fees from edge (2% per side)
        fee_rate = 0.02
        net_edge = edge - fee_rate * 2
        if net_edge <= 0:
            return 0

        # Estimate variance from confidence: lower confidence = higher σ²
        # σ² = edge / confidence → high confidence reduces variance
        variance = max(edge / max(opp.confidence, 0.1), 0.01)

        # Continuous Kelly: f* = μ / σ²
        fraction = net_edge / variance
        fraction = max(0.005, min(fraction, 0.10))  # 0.5% to 10%

        # 1/5 Kelly for safety (quants win the sizing game, not the win-rate game)
        fraction *= 0.20

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
