"""
Polymarket Money Generator

Quantitative arbitrage scanner and monitoring system for Polymarket.
Uses LP optimization, PCA/SVD, GARCH, VaR, and AI analysis to detect
mispricing across prediction markets.

Usage:
    python main.py ui            # Launch web dashboard with simulated $1,000 account
    python main.py scan          # Run one-time scan
    python main.py monitor       # Run continuous terminal monitoring
    python main.py analyze       # Run AI analysis on current markets
"""

from __future__ import annotations

import asyncio
import sys

from src.utils.logger import setup_logger

logger = setup_logger("main")


async def run_scan():
    """Single scan cycle — print results and exit."""
    from src.scanner.market_scanner import MarketScanner

    scanner = MarketScanner()
    result = await scanner.scan_once()

    print(f"\n{'='*70}")
    print(f"  POLYMARKET SCAN RESULTS")
    print(f"  {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Events: {result.events_scanned} | Markets: {result.markets_scanned}")
    print(f"  Scan time: {result.scan_duration_ms:.0f}ms")
    print(f"{'='*70}\n")

    if not result.opportunities:
        print("  No arbitrage opportunities found above threshold.\n")
    else:
        print(f"  Found {len(result.opportunities)} opportunities:\n")
        for i, opp in enumerate(result.opportunities[:20], 1):
            print(f"  {i:2d}. [{opp.opportunity_type}] {opp.edge_pct:.2f}% edge "
                  f"(confidence: {opp.confidence:.0%})")
            print(f"      {opp.description[:90]}")
            print(f"      Capital: ${opp.required_capital:.2f} | "
                  f"Expected profit: ${opp.expected_profit:.2f}")
            if opp.legs:
                for leg in opp.legs[:4]:
                    print(f"        → {leg.get('side', '?')} @ {leg.get('price', 0):.4f} "
                          f"on {leg.get('question', leg.get('market', ''))[:50]}")
            print()

    if result.correlation_info:
        ci = result.correlation_info
        print(f"  Correlation Structure (SVD):")
        print(f"    Factors explaining 80% of variance: {ci['n_factors_80pct']}")
        cum = ci.get("cumulative_variance", [])
        if len(cum) >= 3:
            print(f"    Top 3 components: {cum[2]*100:.1f}% of total variance")
        print()

    if result.ai_relationships:
        violated = [r for r in result.ai_relationships if r.get("violated")]
        if violated:
            print(f"  AI Alerts ({len(violated)} constraint violations):")
            for rel in violated[:5]:
                print(f"    ⚠ [{rel.get('type')}] {rel.get('constraint', 'N/A')}")
                print(f"      {rel.get('reasoning', '')[:80]}")
            print()

    if result.errors:
        print(f"  Errors: {len(result.errors)}")
        for err in result.errors[:5]:
            print(f"    ✗ {err}")

    await scanner.client.close()


async def run_monitor():
    """Run continuous monitoring dashboard."""
    from src.dashboard.dashboard import Dashboard

    dashboard = Dashboard()
    await dashboard.run()


async def run_analyze():
    """Run AI-only analysis on current markets."""
    from config.settings import settings
    from src.api.polymarket_client import PolymarketClient
    from src.ai.market_analyzer import AIMarketAnalyzer

    if not settings.ai.openai_api_key:
        print("Error: LLM_API_KEY (or OPENAI_API_KEY) not set in .env")
        sys.exit(1)

    client = PolymarketClient()
    ai = AIMarketAnalyzer(
        api_key=settings.ai.openai_api_key,
        model=settings.ai.model,
        base_url=settings.ai.base_url,
    )

    print("Fetching markets...")
    events = await client.get_all_active_events(max_pages=3)
    print(f"Analyzing {len(events)} events with AI...")

    relationships = await ai.analyze_event_relationships(events[:15])
    brief = await ai.generate_market_brief(events, [])

    print(f"\n{'='*70}")
    print("  AI MARKET ANALYSIS")
    print(f"{'='*70}\n")
    print(brief)

    if relationships:
        print(f"\n  Detected {len(relationships)} logical relationships:")
        for rel in relationships:
            status = "⚠ VIOLATED" if rel.get("violated") else "✓ OK"
            print(f"\n  {status} [{rel.get('type')}]")
            print(f"    {rel.get('market_a_question', '?')[:60]}")
            print(f"    {rel.get('market_b_question', '?')[:60]}")
            print(f"    Constraint: {rel.get('constraint', 'N/A')}")
            if rel.get("violated"):
                print(f"    Edge: ~{rel.get('edge_estimate_pct', 0):.1f}%")

    await client.close()


def run_ui(balance: float = 1000.0, port: int = 8899):
    """Launch web UI with simulated trading account."""
    from src.web.server import run_server

    print(f"\n{'='*50}")
    print(f"  POLYMARKET MONEY GENERATOR")
    print(f"  Simulated account: ${balance:,.2f}")
    print(f"  Dashboard: http://localhost:{port}")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*50}\n")

    run_server(starting_balance=balance, port=port)


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "ui"

    # Parse optional --balance flag
    balance = 1000.0
    for i, arg in enumerate(sys.argv):
        if arg == "--balance" and i + 1 < len(sys.argv):
            balance = float(sys.argv[i + 1])

    if command == "ui":
        run_ui(balance=balance)
    elif command == "scan":
        asyncio.run(run_scan())
    elif command == "monitor":
        asyncio.run(run_monitor())
    elif command == "analyze":
        asyncio.run(run_analyze())
    else:
        print(f"Unknown command: {command}")
        print("Usage: python main.py [ui|scan|monitor|analyze]")
        print("       python main.py ui --balance 5000")
        sys.exit(1)


if __name__ == "__main__":
    main()
