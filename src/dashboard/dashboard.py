"""
Real-time Monitoring Dashboard

Rich terminal UI showing:
- Live arbitrage opportunities
- Portfolio risk metrics (VaR, Sharpe, drawdown)
- Correlation structure (effective # of bets)
- GARCH volatility status
- AI relationship alerts
- Scan performance metrics
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config.settings import settings
from src.scanner.market_scanner import MarketScanner, ScanResult
from src.utils.data_models import ArbitrageOpportunity
from src.utils.logger import setup_logger

logger = setup_logger("dashboard")
console = Console()


class Dashboard:
    """Rich terminal dashboard for real-time monitoring."""

    def __init__(self):
        self.scanner = MarketScanner()
        self._latest_result: ScanResult | None = None
        self._history: list[ScanResult] = []
        self._start_time = datetime.now()

    async def run(self):
        """Run dashboard with live updates."""
        console.print(Panel(
            "[bold cyan]Polymarket Money Generator[/bold cyan]\n"
            "[dim]Quantitative Arbitrage Scanner & Monitor[/dim]",
            title="🔥 PMG",
            border_style="cyan",
        ))
        console.print()

        with Live(self._build_layout(), refresh_per_second=1, console=console) as live:
            scanner_task = asyncio.create_task(
                self.scanner.run_continuous(callback=self._on_scan_result)
            )
            try:
                while True:
                    live.update(self._build_layout())
                    await asyncio.sleep(settings.dashboard.refresh_seconds)
            except asyncio.CancelledError:
                scanner_task.cancel()
                await scanner_task

    async def _on_scan_result(self, result: ScanResult):
        """Callback when a new scan completes."""
        self._latest_result = result
        self._history.append(result)
        # Keep last 100 results
        if len(self._history) > 100:
            self._history = self._history[-100:]

    def _build_layout(self) -> Layout:
        """Build the full dashboard layout."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3),
        )
        layout["body"].split_row(
            Layout(name="left", ratio=2),
            Layout(name="right", ratio=1),
        )
        layout["left"].split_column(
            Layout(name="opportunities", ratio=2),
            Layout(name="ai_alerts", ratio=1),
        )
        layout["right"].split_column(
            Layout(name="stats"),
            Layout(name="risk"),
            Layout(name="correlation"),
        )

        layout["header"].update(self._build_header())
        layout["opportunities"].update(self._build_opportunities_table())
        layout["ai_alerts"].update(self._build_ai_panel())
        layout["stats"].update(self._build_stats_panel())
        layout["risk"].update(self._build_risk_panel())
        layout["correlation"].update(self._build_correlation_panel())
        layout["footer"].update(self._build_footer())

        return layout

    def _build_header(self) -> Panel:
        uptime = datetime.now() - self._start_time
        scans = len(self._history)
        return Panel(
            f"[bold]Polymarket Money Generator[/bold] │ "
            f"Scans: {scans} │ "
            f"Uptime: {str(uptime).split('.')[0]} │ "
            f"Interval: {settings.scanner.interval_seconds}s │ "
            f"Min Edge: {settings.scanner.min_arbitrage_edge_pct}%",
            style="cyan",
        )

    def _build_opportunities_table(self) -> Panel:
        table = Table(title="Arbitrage Opportunities", expand=True)
        table.add_column("#", width=3)
        table.add_column("Type", width=18)
        table.add_column("Edge %", width=8, justify="right")
        table.add_column("Confidence", width=10, justify="right")
        table.add_column("Capital", width=10, justify="right")
        table.add_column("Description", ratio=1)

        if self._latest_result and self._latest_result.opportunities:
            for i, opp in enumerate(self._latest_result.opportunities[:15], 1):
                edge_color = "green" if opp.edge_pct >= 3 else "yellow" if opp.edge_pct >= 1.5 else "white"
                conf_color = "green" if opp.confidence >= 0.8 else "yellow" if opp.confidence >= 0.5 else "red"

                table.add_row(
                    str(i),
                    opp.opportunity_type[:18],
                    f"[{edge_color}]{opp.edge_pct:.2f}%[/{edge_color}]",
                    f"[{conf_color}]{opp.confidence:.0%}[/{conf_color}]",
                    f"${opp.required_capital:.0f}",
                    opp.description[:80],
                )
        else:
            table.add_row("", "", "", "", "", "[dim]Scanning...[/dim]")

        return Panel(table, border_style="green")

    def _build_ai_panel(self) -> Panel:
        lines: list[str] = []
        if self._latest_result and self._latest_result.ai_relationships:
            for rel in self._latest_result.ai_relationships[:5]:
                violated = "⚠️ " if rel.get("violated") else "✓ "
                lines.append(
                    f"{violated}[{rel.get('type', '?')}] "
                    f"{rel.get('constraint', 'N/A')}: "
                    f"{rel.get('reasoning', '')[:60]}"
                )
        if not lines:
            lines = ["[dim]Waiting for AI analysis...[/dim]"]

        return Panel(
            "\n".join(lines),
            title="AI Relationship Alerts",
            border_style="magenta",
        )

    def _build_stats_panel(self) -> Panel:
        if not self._latest_result:
            return Panel("[dim]Waiting...[/dim]", title="Scan Stats")

        r = self._latest_result
        lines = [
            f"Events:        {r.events_scanned}",
            f"Markets:       {r.markets_scanned}",
            f"Opportunities: {len(r.opportunities)}",
            f"Scan time:     {r.scan_duration_ms:.0f}ms",
        ]
        if r.errors:
            lines.append(f"[red]Errors: {len(r.errors)}[/red]")

        return Panel("\n".join(lines), title="Scan Stats", border_style="blue")

    def _build_risk_panel(self) -> Panel:
        if not self._latest_result or not self._latest_result.risk_metrics:
            return Panel("[dim]N/A[/dim]", title="Risk (VaR)")

        rm = self._latest_result.risk_metrics
        lines = [
            f"VaR 99%:     ${rm.var_99:.2f}",
            f"VaR 95%:     ${rm.var_95:.2f}",
            f"CVaR:        ${rm.expected_shortfall:.2f}",
            f"Sharpe:      {rm.sharpe_ratio:.2f}",
            f"Max DD:      {rm.max_drawdown:.2%}",
            f"Vol (ann.):  {rm.volatility:.2%}",
        ]

        return Panel("\n".join(lines), title="Risk Metrics", border_style="red")

    def _build_correlation_panel(self) -> Panel:
        if not self._latest_result or not self._latest_result.correlation_info:
            return Panel("[dim]N/A[/dim]", title="Structure (SVD)")

        ci = self._latest_result.correlation_info
        lines = [
            f"Factors (80%): {ci.get('n_factors_80pct', '?')}",
        ]
        cum = ci.get("cumulative_variance", [])
        if cum:
            lines.append(f"PC1 explains:  {cum[0]*100:.1f}%")
            if len(cum) >= 3:
                lines.append(f"Top 3 explain: {cum[2]*100:.1f}%")

        return Panel("\n".join(lines), title="Correlation", border_style="yellow")

    def _build_footer(self) -> Panel:
        return Panel(
            "[dim]Press Ctrl+C to stop │ "
            "Dry-run mode — no real trades │ "
            f"Config: min_edge={settings.scanner.min_arbitrage_edge_pct}% "
            f"min_liq=${settings.scanner.min_liquidity_usd}[/dim]",
            style="dim",
        )
