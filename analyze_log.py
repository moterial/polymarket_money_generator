"""Comprehensive log analysis of the trading engine run."""
import json, sys
from collections import Counter
from datetime import datetime

d = json.load(open(sys.argv[1]))

print("=" * 70)
print("  FULL STATE ANALYSIS")
print("=" * 70)

# Account overview
print(f"\n--- ACCOUNT ---")
print(f"  Starting Balance: ${d.get('starting_balance', 1000):.2f}")
print(f"  Cash Balance:     ${d.get('balance', 0):.2f}")
print(f"  Equity:           ${d.get('equity', 0):.2f}")
print(f"  Total P&L:        ${d.get('total_pnl', 0):.2f} ({d.get('total_pnl_pct', 0):.2f}%)")
print(f"  Total Trades:     {d.get('total_trades', 0)}")
print(f"  Winning Trades:   {d.get('winning_trades', 0)}")
print(f"  Losing Trades:    {d.get('losing_trades', 0)}")
print(f"  Win Rate:         {d.get('win_rate', 0):.1%}")
print(f"  Scan Count:       {d.get('scan_count', 0)}")

# Positions
positions = d.get("positions", [])
print(f"\n--- OPEN POSITIONS ({len(positions)}) ---")
total_unrealized = 0
for p in positions:
    upnl = p.get("unrealized_pnl", 0)
    total_unrealized += upnl
    entry = p.get("avg_entry_price", 0)
    cur = p.get("current_price", 0)
    pct = ((cur - entry) / entry * 100) if entry > 0 else 0
    q = p.get("market_question", "?")[:55]
    side = p.get("side", "?")
    size = p.get("size", 0)
    cost = p.get("cost_basis", 0)
    mval = p.get("market_value", 0)
    print(f"  {side:8s} | {q}")
    print(f"           Entry: {entry:.4f} → Now: {cur:.4f} ({pct:+.1f}%) | Size: {size:.1f} | Cost: ${cost:.2f} | Val: ${mval:.2f} | uPnL: ${upnl:.2f}")
print(f"  TOTAL unrealized: ${total_unrealized:.2f}")

# Order history
orders = d.get("orders", [])
print(f"\n--- ORDER HISTORY ({len(orders)} orders) ---")

# Analyze realized P&L from closed trades
realized_pnl_orders = [o for o in orders if o.get("pnl") is not None and o.get("pnl") != 0]
buy_orders = [o for o in orders if "BUY" in o.get("side", "")]
sell_orders = [o for o in orders if "SELL" in o.get("side", "")]
print(f"  Buy orders:  {len(buy_orders)}")
print(f"  Sell orders: {len(sell_orders)}")
print(f"  Orders with realized P&L: {len(realized_pnl_orders)}")
if realized_pnl_orders:
    for o in realized_pnl_orders:
        q = o.get("market_question", "?")[:50]
        print(f"    {o.get('side','')} {q} → P&L: ${o['pnl']:.2f} | Reason: {o.get('reason','')[:40]}")

# Fee analysis
total_fees = 0
for o in orders:
    cost = o.get("cost", 0)
    size = o.get("size", 0)
    price = o.get("price", 0)
    expected = size * price
    if "BUY" in o.get("side", ""):
        fee = cost - expected if cost > expected else 0
    else:
        fee = expected - cost if expected > cost else 0
    total_fees += fee
print(f"\n  Estimated total fees: ${total_fees:.2f}")

# Decision log
decisions = d.get("decisions", [])
print(f"\n--- DECISION LOG ({len(decisions)} entries) ---")
action_counts = Counter(dd.get("action", "?") for dd in decisions)
for action, count in action_counts.most_common():
    print(f"  {action}: {count}")

# Print trade decisions specifically
trade_decisions = [dd for dd in decisions if dd.get("action") in ("TRADE", "TAKE_PROFIT", "STOP_LOSS", "TIME_EXIT")]
print(f"\n--- KEY TRADE DECISIONS ({len(trade_decisions)}) ---")
for dd in trade_decisions:
    ts = dd.get("timestamp", "?")
    action = dd.get("action", "?")
    market = dd.get("market", "?")[:50]
    reason = dd.get("reason", "")[:60]
    edge = dd.get("edge_pct", 0)
    print(f"  [{ts}] {action} | {market}")
    if edge:
        print(f"    edge={edge:.1f}% | {reason}")
    elif reason:
        print(f"    {reason}")

# Check for patterns/issues
print(f"\n--- PATTERN ANALYSIS ---")

# Same market re-entry
market_trades = Counter()
for dd in decisions:
    if dd.get("action") == "TRADE":
        m = dd.get("market", "?")
        market_trades[m] += 1
repeat_trades = {m: c for m, c in market_trades.items() if c > 1}
if repeat_trades:
    print(f"  Markets traded multiple times:")
    for m, c in repeat_trades.items():
        print(f"    {m[:50]}: {c} times")

# Time exit analysis
time_exits = [dd for dd in decisions if dd.get("action") == "TIME_EXIT"]
print(f"  Time exits: {len(time_exits)}")

# TP/SL analysis
tp = [dd for dd in decisions if dd.get("action") == "TAKE_PROFIT"]
sl = [dd for dd in decisions if dd.get("action") == "STOP_LOSS"]
print(f"  Take profits: {len(tp)}")
print(f"  Stop losses: {len(sl)}")

# Scan timing
print(f"\n--- EFFICIENCY ---")
print(f"  Total scans: {d.get('scan_count', 0)}")
print(f"  Engine running: {d.get('engine_running', False)}")
