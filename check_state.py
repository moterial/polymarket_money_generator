import json, sys

d = json.load(open(sys.argv[1]))
print("Scans:", d.get("scan_count", 0))
print("Positions:", d.get("open_positions", 0))
print("PnL:", d.get("total_pnl", 0))
print("Equity:", d.get("equity", 0))
decisions = d.get("decisions", [])
print(f"Decisions: {len(decisions)}")
for x in decisions[:10]:
    action = x.get("action", "?")
    market = x.get("market", "?")[:40]
    edge = x.get("edge_pct", 0)
    print(f"  {action} | {market} | edge={edge:.1f}%")
