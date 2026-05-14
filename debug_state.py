import json, sys

with open(sys.argv[1]) as f:
    d = json.load(f)

print("=== Account ===")
print(f"Cash:     {d['balance']:>10.2f}")
print(f"Equity:   {d['equity']:>10.2f}")
print(f"Start:    {d['starting_balance']:>10.2f}")
print(f"TotalPnL: {d['total_pnl']:>10.2f} ({d['total_pnl_pct']:.1f}%)")
print(f"RealPnL:  {d['realized_pnl']:>10.2f}")
print(f"UnrealPnL:{d['unrealized_pnl']:>10.2f}")
print(f"Fees:     {d['total_fees']:>10.2f}")
print(f"Trades:{d['trade_count']} W:{d['win_count']} L:{d['loss_count']} WR:{d['win_rate']}%")
print(f"Scans: {d['scan_count']}")
print()

# Check accounting identity
pos_value = sum(p['market_value'] for p in d['positions'])
pos_cost = sum(p['cost_basis'] for p in d['positions'])
expected_equity = d['balance'] + pos_value
print("=== Accounting Check ===")
print(f"Positions market_value sum: {pos_value:.2f}")
print(f"Positions cost_basis sum:   {pos_cost:.2f}")
print(f"Cash + pos_value:           {expected_equity:.2f}")
print(f"Reported equity:            {d['equity']:.2f}")
print(f"MATCH: {abs(expected_equity - d['equity']) < 0.01}")
print(f"Expected TotalPnL:          {expected_equity - d['starting_balance']:.2f}")
print(f"Reported TotalPnL:          {d['total_pnl']:.2f}")
print()

print("=== Positions ===")
for p in d['positions']:
    q = p['market_question'][:40]
    print(f"  {p['side']:8} sz={p['size']:6.1f} entry={p['avg_entry_price']:.4f} cur={p['current_price']:.4f} cost={p['cost_basis']:7.2f} mval={p['market_value']:7.2f} upnl={p['unrealized_pnl']:7.2f} | {q}")
print()

print("=== Last 15 Orders ===")
for o in d['recent_orders'][:15]:
    pnl_str = f"{o['pnl']:>7.2f}" if o.get('pnl') is not None else "   -   "
    q = o['market_question'][:35]
    print(f"  {o['status']:9} {o['side']:8} sz={o['size']:6.1f} @{o['price']:.4f} cost={o['cost']:7.2f} pnl={pnl_str} | {q}")
