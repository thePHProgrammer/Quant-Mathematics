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
1. Paste `trading_context_pack.pine` into the Pine Editor, add it to a chart (any TF from 1m to 1D).
   With `Auto`, the HTF and LTF follow the table in `docs/SPEC.md` (e.g. 5m chart → 1m / 1H,
   15m → 5m / 4H, 1H → 5m / 1D).
2. HTF zones are drawn with a thick solid border, chart-TF zones with a thin border, and LTF zones
   dashed. Bold **BUY AOI / SELL AOI** boxes mark the areas of interest. ▲/▼ markers are setups
   that triggered.
3. To test whether it has an edge, add `mtf_zone_strategy.pine` and follow §11 of `docs/SPEC.md`:
   in-sample → out-of-sample, models A–F and A+X, realistic costs.

## Editing the engine
Edit the block between `ENGINE START` / `ENGINE END` in `trading_context_pack.pine`, then run:
```
python3 tools/sync_engine.py          # copy into the strategy
python3 tools/sync_engine.py --check  # verify both copies match
```
