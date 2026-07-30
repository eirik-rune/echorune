#!/usr/bin/env python3
"""echorune books: Cash Flow / P&L / Slices from two CSVs. stdlib only.
  treasury.csv  cash, chain-verifiable (txhash per row)
  ledger.csv    accrued labour -> P&L expense + slices (ownership)
Usage: python3 ops/books.py [--verify]   (--verify checks chain balance)"""
import csv, os, sys, json, urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT = "0xbc52B57679a732074456C0DD037380f6D0Ce3f57"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
FX_RMB_USD = 7.2   # fixed booking rate (policy, shareholder 7/30); USD is the reporting currency

def rows(name):
    p = os.path.join(ROOT, name)
    if not os.path.exists(p): return []
    with open(p, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("date")]

def chain():
    def rpc(m, p):
        req = urllib.request.Request("https://mainnet.base.org",
            data=json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),
            headers={"Content-Type":"application/json","User-Agent":"echorune-books"})
        return json.load(urllib.request.urlopen(req, timeout=20)).get("result")
    eth = int(rpc("eth_getBalance",[VAULT,"latest"]),16)/1e18
    b = rpc("eth_call",[{"to":USDC,"data":"0x70a08231"+VAULT[2:].rjust(64,"0")},"latest"])
    return eth, (int(b,16)/1e6 if b and b!="0x" else 0.0)

T, L = rows("treasury.csv"), rows("ledger.csv")

# ---------- CASH FLOW ----------
inflow, outflow, pending = defaultdict(float), defaultdict(float), []
cf_by_cat = defaultdict(float)
for r in T:
    a, asset = float(r["amount"]), r["asset"].upper()
    if r["dir"] == "in": inflow[asset] += a
    else:
        outflow[asset] += a
        cf_by_cat[r.get("category") or "uncategorized"] += a
        if not (r.get("txhash") or "").startswith("0x"): pending.append(r)

print("=" * 62)
print("CASH FLOW  (cash basis, chain-verifiable)")
print("=" * 62)
if not T:
    print("  no cash movements yet -- vault funded: never")
for asset in sorted(set(inflow) | set(outflow)):
    net = inflow[asset] - outflow[asset]
    print("  %-5s in %+12.6f   out %-12.6f   net %+12.6f" % (asset, inflow[asset], outflow[asset], net))
if cf_by_cat:
    print("  -- outflow by category --")
    for k, v in sorted(cf_by_cat.items(), key=lambda x: -x[1]):
        print("     %-22s %10.4f" % (k, v))
if pending:
    print("  !! %d row(s) WITHOUT txhash -> unverifiable, treat as claim not fact" % len(pending))

# ---------- P&L ----------
rev = sum(float(r["amount"]) for r in T if r["dir"] == "in" and (r.get("category") or "") != "capital")
capital = sum(float(r["amount"]) for r in T if r["dir"] == "in" and (r.get("category") or "") == "capital")
cash_exp = sum(float(r["amount"]) for r in T if r["dir"] == "out")
labour, hours, bad = defaultdict(float), defaultdict(float), []
for r in L:
    if r.get("type") != "time": continue
    h, rate, fx = float(r["hours"]), float(r["rate_rmb_h"]), float(r["fx"])
    usd = float(r["amount_usd"])
    if abs(h * rate / fx - usd) > 0.02: bad.append((r["partner"], r["date"], usd, h * rate / fx))
    labour[r["partner"]] += usd
    hours[r["partner"]] += h
labour_total = sum(labour.values())

print()
print("=" * 62)
print("P&L  (USD reporting currency, FX %.2f fixed; labour settled in SLICES not cash)" % FX_RMB_USD)
print("=" * 62)
print("  Revenue (tips/services)        %10.2f USD" % rev)
print("  Cash expenses (infra/api)      %10.2f" % -cash_exp)
print("  Gross margin                   %10.2f" % (rev - cash_exp))
print("  -- equity-settled labour (non-cash, NO payable) --")
for k in sorted(labour):
    print("     %-8s %5.1f h  %8.2f USD" % (k, hours[k], labour[k]))
print("  Labour total                   %10.2f" % -labour_total)
print("  NET PROFIT / (LOSS)            %10.2f USD" % (rev - cash_exp - labour_total))
if bad:
    print("  !! %d ledger row(s) fail amount_usd == hours*rate/fx : %s" % (len(bad), bad))
print("  memo: capital injected %.2f (financing, NOT revenue)" % capital)

# ---------- SLICES ----------
sl = defaultdict(float)
for r in L: sl[r["partner"]] += float(r.get("slices") or 0)
tot = sum(sl.values()) or 1
print()
print("=" * 62)
print("SLICES  (ownership, not cash)")
print("=" * 62)
for k in sorted(sl, key=lambda x: -sl[x]):
    print("  %-12s %9.0f  %5.1f%%" % (k, sl[k], 100 * sl[k] / tot))
print("  %-12s %9.0f" % ("TOTAL", tot))

# ---------- RECONCILE ----------
if "--verify" in sys.argv:
    eth, usdc = chain()
    print()
    print("=" * 62)
    print("RECONCILE  ledger vs chain")
    print("=" * 62)
    for asset, onchain in (("ETH", eth), ("USDC", usdc)):
        book = inflow[asset] - outflow[asset]
        d = onchain - book
        print("  %-5s book %+14.6f  chain %+14.6f  diff %+.6f  %s"
              % (asset, book, onchain, d, "OK" if abs(d) < 1e-9 else "MISMATCH -> unrecorded movement"))
