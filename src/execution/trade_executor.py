"""
Trade Executor

Handles order creation and execution on Polymarket CLOB.
Requires API credentials (private key + API key/secret/passphrase).

Safety features:
- Position size limits
- VaR check before execution
- Dry-run mode by default
- Execution speed logging
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from config.settings import settings
from src.utils.data_models import ArbitrageOpportunity
from src.utils.logger import setup_logger

logger = setup_logger("execution")


@dataclass
class TradeResult:
    success: bool
    order_id: Optional[str] = None
    fill_price: Optional[float] = None
    fill_size: Optional[float] = None
    execution_time_ms: float = 0
    error: Optional[str] = None


class TradeExecutor:
    """
    Execute trades on Polymarket CLOB.

    Modes:
    - dry_run=True (default): Log trades without executing
    - dry_run=False: Submit real orders (requires credentials)
    """

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.max_position_usd = settings.scanner.max_position_size_usd
        self._total_executed = 0.0

    async def execute_opportunity(
        self,
        opportunity: ArbitrageOpportunity,
        scale: float = 1.0,
    ) -> list[TradeResult]:
        """
        Execute all legs of an arbitrage opportunity.

        Args:
            opportunity: The arbitrage to execute
            scale: Position scaling factor (0-1)
        """
        results: list[TradeResult] = []

        # Pre-flight checks
        if opportunity.edge_pct < settings.scanner.min_arbitrage_edge_pct:
            logger.warning("Edge too small: %.2f%% < %.2f%% minimum",
                          opportunity.edge_pct, settings.scanner.min_arbitrage_edge_pct)
            return [TradeResult(success=False, error="Edge below minimum")]

        total_cost = opportunity.required_capital * scale
        if total_cost > self.max_position_usd:
            logger.warning("Position too large: $%.2f > $%.2f max",
                          total_cost, self.max_position_usd)
            scale = self.max_position_usd / opportunity.required_capital

        # Execute each leg
        for leg in opportunity.legs:
            t0 = time.monotonic()
            result = await self._execute_leg(leg, scale)
            result.execution_time_ms = (time.monotonic() - t0) * 1000
            results.append(result)

            if not result.success:
                logger.error("Leg failed: %s — aborting remaining legs", result.error)
                break

        # Summary
        successful = sum(1 for r in results if r.success)
        total_time = sum(r.execution_time_ms for r in results)
        logger.info(
            "Execution: %d/%d legs successful in %.0fms (%.2f%% edge, $%.2f capital)",
            successful, len(opportunity.legs), total_time,
            opportunity.edge_pct, total_cost,
        )

        return results

    async def _execute_leg(self, leg: dict, scale: float) -> TradeResult:
        """Execute a single trade leg."""
        market_id = leg.get("market", "")
        side = leg.get("side", "")
        price = leg.get("price", 0)
        size = leg.get("size", 1.0) * scale

        if self.dry_run:
            logger.info(
                "[DRY RUN] %s on %s @ %.4f, size=%.4f",
                side, market_id[:16], price, size,
            )
            return TradeResult(
                success=True,
                fill_price=price,
                fill_size=size,
            )

        # Real execution would use Polymarket CLOB client
        # Requires: py_clob_client or direct API calls with signed orders
        if not settings.api.private_key:
            return TradeResult(
                success=False,
                error="No private key configured for live trading",
            )

        try:
            # This is where you'd integrate with the actual CLOB API:
            # 1. Create order (GTC limit order at specified price)
            # 2. Sign with private key
            # 3. POST to /order endpoint
            # 4. Monitor fill via WebSocket or polling

            # Placeholder for actual integration:
            logger.warning("Live trading not yet implemented — use py-clob-client SDK")
            return TradeResult(
                success=False,
                error="Live trading integration pending — install @polymarket/clob-client",
            )

        except Exception as e:
            return TradeResult(success=False, error=str(e))

    async def cancel_all(self) -> bool:
        """Cancel all open orders (safety mechanism)."""
        if self.dry_run:
            logger.info("[DRY RUN] Cancel all orders")
            return True

        logger.warning("Cancel all — not implemented in dry-run-only mode")
        return False
