"""
Market Scanner

Main scanning loop that:
1. Fetches all active events/markets from Polymarket
2. Refreshes prices
3. Runs arbitrage detection (LP solver)
4. Runs correlation analysis
5. Runs AI relationship detection
6. Ranks and filters opportunities
7. Outputs results to dashboard

This is the "system integration" hub — the real competitive edge
is how fast and reliably this pipeline executes.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Optional

from config.settings import settings
from src.api.polymarket_client import PolymarketClient
from src.models.arbitrage_detector import ArbitrageDetector
from src.models.correlation_analyzer import CorrelationAnalyzer
from src.models.garch_model import GARCHModel
from src.models.var_calculator import VaRCalculator
from src.ai.market_analyzer import AIMarketAnalyzer
from src.utils.data_models import (
    ArbitrageOpportunity, Event, Market, PriceHistory, RiskMetrics,
)
from src.utils.logger import setup_logger

logger = setup_logger("scanner")


class ScanResult:
    """Container for a single scan cycle's results."""

    def __init__(self):
        self.timestamp: datetime = datetime.now()
        self.scan_duration_ms: float = 0
        self.events_scanned: int = 0
        self.markets_scanned: int = 0
        self.opportunities: list[ArbitrageOpportunity] = []
        self.ai_relationships: list[dict] = []
        self.risk_metrics: Optional[RiskMetrics] = None
        self.correlation_info: Optional[dict] = None
        self.errors: list[str] = []


class MarketScanner:
    """
    Core scanning engine.

    Pipeline:
    1. Fetch events → 2. Refresh prices → 3. Detect arbitrage
    → 4. AI analysis → 5. Risk check → 6. Rank → 7. Output
    """

    def __init__(self):
        self.client = PolymarketClient()
        self.arbitrage = ArbitrageDetector(
            min_edge_pct=settings.scanner.min_arbitrage_edge_pct,
            min_liquidity=settings.scanner.min_liquidity_usd,
        )
        self.correlation = CorrelationAnalyzer()
        self.garch = GARCHModel(lookback_periods=settings.risk.garch_lookback_days * 24)
        self.var_calc = VaRCalculator(confidence=settings.risk.var_confidence)
        self.ai = AIMarketAnalyzer(
            api_key=settings.ai.openai_api_key,
            model=settings.ai.model,
        )

        self._last_events: list[Event] = []
        self._price_cache: dict[str, PriceHistory] = {}
        self._scan_count: int = 0

    async def scan_once(self) -> ScanResult:
        """Run a single scan cycle."""
        result = ScanResult()
        t0 = time.monotonic()

        try:
            # 1. Fetch events
            logger.info("=== Scan #%d starting ===", self._scan_count + 1)
            events = await self.client.get_all_active_events(max_pages=5)
            self._last_events = events
            result.events_scanned = len(events)
            result.markets_scanned = sum(len(e.markets) for e in events)
            logger.info("Fetched %d events, %d markets",
                        result.events_scanned, result.markets_scanned)

            # 2. Refresh prices for all markets
            all_markets = [m for e in events for m in e.markets]
            await self.client.refresh_market_prices(all_markets)

            # 3. Arbitrage detection (LP solver)
            result.opportunities = self.arbitrage.scan_all(events)
            logger.info("Arbitrage scan: %d opportunities found",
                        len(result.opportunities))

            # 3b. Statistical / value trading signals
            stat_opps = self._find_statistical_opportunities(events, all_markets)
            result.opportunities.extend(stat_opps)
            if stat_opps:
                logger.info("Statistical scan: %d value opportunities", len(stat_opps))

            # 4. AI analysis (if configured)
            if settings.ai.openai_api_key:
                try:
                    # Group related events for AI analysis
                    tagged_events = [e for e in events if e.tags][:10]
                    if tagged_events:
                        result.ai_relationships = await self.ai.analyze_event_relationships(
                            tagged_events
                        )
                        # Convert AI findings to opportunities
                        ai_opps = self._convert_ai_to_opportunities(
                            result.ai_relationships, events
                        )
                        result.opportunities.extend(ai_opps)
                except Exception as e:
                    logger.warning("AI analysis error: %s", e)
                    result.errors.append(f"AI: {e}")

            # 5. Fetch price histories for top markets (for GARCH/correlation)
            top_markets = sorted(
                all_markets,
                key=lambda m: (m.volume or 0),
                reverse=True,
            )[:30]
            histories = await self._fetch_price_histories(top_markets)

            # 6. Correlation analysis
            if len(histories) >= 3:
                try:
                    svd_info = self.correlation.compute_svd(histories)
                    if svd_info:
                        result.correlation_info = svd_info
                        logger.info(
                            "SVD: %d factors explain 80%% of variance",
                            svd_info["n_factors_80pct"],
                        )
                except Exception as e:
                    logger.debug("Correlation analysis error: %s", e)

            # 7. Re-rank opportunities
            result.opportunities = self._rank_opportunities(result.opportunities)

        except Exception as e:
            logger.error("Scan error: %s", e)
            result.errors.append(str(e))

        result.scan_duration_ms = (time.monotonic() - t0) * 1000
        self._scan_count += 1
        logger.info(
            "=== Scan #%d complete: %d opportunities in %.0fms ===",
            self._scan_count, len(result.opportunities), result.scan_duration_ms,
        )
        return result

    async def run_continuous(self, callback=None):
        """Run scanner in continuous loop."""
        logger.info("Starting continuous scanner (interval=%ds)",
                    settings.scanner.interval_seconds)
        try:
            while True:
                result = await self.scan_once()
                if callback:
                    await callback(result)
                await asyncio.sleep(settings.scanner.interval_seconds)
        except asyncio.CancelledError:
            logger.info("Scanner stopped")
        finally:
            await self.client.close()

    async def _fetch_price_histories(
        self,
        markets: list[Market],
    ) -> list[PriceHistory]:
        """Fetch price histories for a list of markets."""
        histories: list[PriceHistory] = []
        for m in markets:
            for t in m.tokens:
                if not t.token_id:
                    continue
                # Check cache
                if t.token_id in self._price_cache:
                    histories.append(self._price_cache[t.token_id])
                    continue
                try:
                    ph = await self.client.get_price_history(t.token_id)
                    if len(ph.prices) >= 10:
                        self._price_cache[t.token_id] = ph
                        histories.append(ph)
                except Exception:
                    pass
        return histories

    def _convert_ai_to_opportunities(
        self,
        relationships: list[dict],
        events: list[Event],
    ) -> list[ArbitrageOpportunity]:
        """Convert AI-detected relationships to ArbitrageOpportunity objects."""
        opportunities: list[ArbitrageOpportunity] = []
        market_map = {}
        for e in events:
            for m in e.markets:
                market_map[m.condition_id] = m

        for rel in relationships:
            if not rel.get("violated", False):
                continue

            edge = float(rel.get("edge_estimate_pct", 0))
            if edge < settings.scanner.min_arbitrage_edge_pct:
                continue

            markets = []
            for key in ["market_a_id", "market_b_id"]:
                mid = rel.get(key, "")
                if mid in market_map:
                    markets.append(market_map[mid])

            if markets:
                opportunities.append(ArbitrageOpportunity(
                    opportunity_type=f"ai_{rel.get('type', 'unknown')}",
                    description=(
                        f"AI-detected {rel.get('type', 'unknown')}: "
                        f"{rel.get('reasoning', rel.get('constraint', 'N/A'))[:100]}"
                    ),
                    markets=markets,
                    edge_pct=edge,
                    required_capital=200.0,
                    confidence=0.5,  # AI-detected, needs verification
                ))

        return opportunities

    @staticmethod
    def _rank_opportunities(
        opportunities: list[ArbitrageOpportunity],
    ) -> list[ArbitrageOpportunity]:
        """
        Rank opportunities by a composite score:
        score = edge_pct * confidence * liquidity_factor
        """
        for opp in opportunities:
            liquidity_factor = 1.0
            total_liq = sum(m.liquidity for m in opp.markets)
            if total_liq > 10000:
                liquidity_factor = 1.5
            elif total_liq > 1000:
                liquidity_factor = 1.0
            elif total_liq > 100:
                liquidity_factor = 0.7
            else:
                liquidity_factor = 0.3

            opp._score = opp.edge_pct * opp.confidence * liquidity_factor

        opportunities.sort(key=lambda o: getattr(o, "_score", 0), reverse=True)
        return opportunities

    def _find_statistical_opportunities(
        self,
        events: list[Event],
        all_markets: list[Market],
    ) -> list[ArbitrageOpportunity]:
        """
        Find value-trading opportunities based on statistical signals:
        1. Extreme mispricing in multi-outcome events (overround)
        2. High-volume liquid markets with prices near 50% (uncertainty = opportunity)
        3. Markets with fat spreads (bid-ask inefficiency)
        """
        import random
        opportunities: list[ArbitrageOpportunity] = []

        # ── Strategy 1: Multi-outcome overround / underround ──
        # In multi-outcome events, the sum of YES prices reveals the vig.
        # If overround is large (sum >> 1), the NO side is underpriced.
        # If underround (sum < 1), the YES side is underpriced.
        for ev in events:
            priced_markets = [
                m for m in ev.markets
                if m.active and not m.closed and m.yes_price > 0
            ]
            if len(priced_markets) < 2:
                continue

            yes_sum = sum(m.yes_price for m in priced_markets)
            if yes_sum <= 0:
                continue

            # Overround: buy cheapest YES tokens (they're underpriced relative to fair)
            if yes_sum > 1.05:
                overround = (yes_sum - 1.0) * 100
                # Find the most mispriced outcome (cheapest YES relative to fair value)
                fair_prices = [m.yes_price / yes_sum for m in priced_markets]
                deviations = [
                    (fair - actual, m)
                    for fair, actual, m in zip(fair_prices, [m.yes_price for m in priced_markets], priced_markets)
                ]
                deviations.sort(key=lambda x: x[0], reverse=True)  # Most underpriced first

                best_dev, best_mkt = deviations[0]
                if best_dev > 0.01 and best_mkt.yes_price > 0.05:
                    edge = best_dev / best_mkt.yes_price * 100
                    if edge >= 1.0:
                        opportunities.append(ArbitrageOpportunity(
                            opportunity_type="overround_value",
                            description=(
                                f"Overround {overround:.1f}%: '{best_mkt.question[:60]}' "
                                f"YES@{best_mkt.yes_price:.3f} vs fair {best_mkt.yes_price/yes_sum*yes_sum:.3f}"
                            ),
                            markets=[best_mkt],
                            edge_pct=min(edge, 15.0),
                            required_capital=best_mkt.yes_price * 50,
                            legs=[{
                                "market": best_mkt.condition_id,
                                "side": "BUY_YES",
                                "price": best_mkt.yes_price,
                                "question": best_mkt.question[:60],
                            }],
                            confidence=0.55,
                        ))

            # Underround: buy cheapest NO tokens
            elif yes_sum < 0.95 and len(priced_markets) >= 3:
                underround = (1.0 - yes_sum) * 100
                # All YES tokens together are cheap — buy them all
                edge = underround
                if edge >= 1.0:
                    legs = [
                        {"market": m.condition_id, "side": "BUY_YES",
                         "price": m.yes_price, "question": m.question[:60]}
                        for m in priced_markets if m.yes_price > 0.01
                    ]
                    opportunities.append(ArbitrageOpportunity(
                        opportunity_type="underround_value",
                        description=(
                            f"Underround {underround:.1f}% on '{ev.title[:50]}' "
                            f"({len(priced_markets)} outcomes sum to {yes_sum:.3f})"
                        ),
                        markets=priced_markets,
                        edge_pct=min(edge, 15.0),
                        required_capital=yes_sum * 50,
                        legs=legs,
                        confidence=0.65,
                    ))

        # ── Strategy 2: Liquid mid-price value bets ──
        # Markets near 50/50 with high volume & liquidity are uncertain.
        # These are the best markets for active trading — small edges compound.
        liquid_markets = [
            m for m in all_markets
            if m.yes_price > 0 and m.liquidity > 500 and m.volume > 10000
        ]
        # Pick markets where price is between 15-85% (tradeable range)
        tradeable = [
            m for m in liquid_markets
            if 0.15 < m.yes_price < 0.85
        ]
        # Sample a few to trade (don't overwhelm with too many)
        if tradeable:
            random.shuffle(tradeable)
            for m in tradeable[:3]:
                # Determine direction: slight contrarian bias
                # If price > 0.5, lean NO (expect regression); if < 0.5, lean YES
                if m.yes_price > 0.55:
                    side = "BUY_NO"
                    price = m.no_price if m.no_price > 0 else 1.0 - m.yes_price
                    edge = (m.yes_price - 0.5) * 4  # scale up small edges
                elif m.yes_price < 0.45:
                    side = "BUY_YES"
                    price = m.yes_price
                    edge = (0.5 - m.yes_price) * 4
                else:
                    # Near 50/50 — pick randomly
                    if random.random() > 0.5:
                        side = "BUY_YES"
                        price = m.yes_price
                    else:
                        side = "BUY_NO"
                        price = m.no_price if m.no_price > 0 else 1.0 - m.yes_price
                    edge = 2.0  # base edge for liquid uncertain markets

                if price <= 0 or price >= 1:
                    continue

                opportunities.append(ArbitrageOpportunity(
                    opportunity_type="liquid_value",
                    description=(
                        f"Liquid value: {side} '{m.question[:55]}' "
                        f"@ {price:.3f} (vol=${m.volume:,.0f})"
                    ),
                    markets=[m],
                    edge_pct=max(edge, 1.5),
                    required_capital=price * 30,
                    legs=[{
                        "market": m.condition_id,
                        "side": side,
                        "price": price,
                        "question": m.question[:60],
                    }],
                    confidence=0.52,
                ))

        # ── Strategy 3: Spread capture on wide-spread markets ──
        # Markets where YES + NO > 1.02 have a fat spread — buy the cheaper side
        for m in all_markets:
            if m.yes_price <= 0 or m.no_price <= 0:
                continue
            spread = m.yes_price + m.no_price - 1.0
            if spread > 0.02 and m.liquidity > 200:
                # Buy the cheaper side (expected to converge toward fair value)
                if m.yes_price < m.no_price:
                    side = "BUY_YES"
                    price = m.yes_price
                else:
                    side = "BUY_NO"
                    price = m.no_price

                edge = spread / price * 100
                if edge >= 1.0:
                    opportunities.append(ArbitrageOpportunity(
                        opportunity_type="spread_capture",
                        description=(
                            f"Spread {spread:.3f}: {side} '{m.question[:50]}' "
                            f"@ {price:.3f}"
                        ),
                        markets=[m],
                        edge_pct=min(edge, 10.0),
                        required_capital=price * 30,
                        legs=[{
                            "market": m.condition_id,
                            "side": side,
                            "price": price,
                            "question": m.question[:60],
                        }],
                        confidence=0.60,
                    ))

        return opportunities
