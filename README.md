# Quant-Mathematics

TradingView Pine Script v6 tools for multi-timeframe market structure, built so that each signal is
defined precisely enough to backtest.

| File | What it is |
|---|---|
| `trading_context_pack.pine` | Indicator: COT, Volume Profile, Delta, S&D, CISD, SMT, Kill Zones **+ MTF engine** (HTF / chart / LTF order blocks, FVGs and swings; Buy/Sell areas of interest; setups with stop/target; alerts). |
| `mtf_zone_strategy.pine` | Strategy that runs the same engine, with an A–F model selector and an R-based stats table. |
| `docs/SPEC.md` | Every rule, the timeframe table, the model ladder, cost/fill assumptions and the research protocol. |
| `tools/sync_engine.py` | Keeps the engine block identical in both Pine files. |

## Quick start
1. Paste `trading_context_pack.pine` into the Pine Editor and add it to a chart (any TF from 1m to 1D).
   With `Auto`, the HTF and LTF follow the table in `docs/SPEC.md` (e.g. 5m chart → 1m / 1H,
   15m → 5m / 4H, 1H → 5m / 1D).
2. **Display mode** (top of the settings):
   - **Clean** (default): only the nearest **A+ / A BUY ZONE / SELL ZONE** boxes, trade markers and a compact table.
   - **Standard**: adds HTF zones, swings and Premium/Discount.
   - **Full**: everything, including the original COT / Volume Profile / S&D / CISD / SMT tools.
3. Each zone label shows three separate things:
   - its **quality grade**: A+ = all 4 checks pass (lower-TF overlap, HTF trend, Discount/Premium, liquidity sweep at the zone); A = 3 of 4
   - its **setup status**: Waiting / Armed / In trade / ...
   - its **past results** under the current settings, e.g. `won 61% of 38 · avg +0.42R · in-sample`

   These are past results, not the odds of the next trade. Turn on *Grade diagnostics* to see each check.
4. COT is off by default. It only works on futures charts (e.g. COMEX:GC1!), not on OANDA:XAUUSD.
5. To test whether it has an edge, add `mtf_zone_strategy.pine` and follow §11 and §15 of `docs/SPEC.md`.

## Editing the engine
Edit the block between `ENGINE START` / `ENGINE END` in `trading_context_pack.pine`, then run:
```
python3 tools/sync_engine.py          # copy into the strategy
python3 tools/sync_engine.py --check  # verify both copies match
```
