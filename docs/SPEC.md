# MTF Zone Engine — Specification and Research Protocol

This document defines every rule used by the MTF engine shared by
`trading_context_pack.pine` (indicator) and `mtf_zone_strategy.pine` (backtest harness).
The goal is a **reproducible, testable trading hypothesis**, not a picture of every signal.

> Status: written without access to the Pine compiler. If TradingView reports a compile error,
> note the file, line number and message so that line can be fixed.

---

## 1. Files

| File | Role |
|---|---|
| `trading_context_pack.pine` | Indicator: original COT / VP / Delta / S&D / CISD / SMT tools **plus** the MTF engine (zones, AOIs, setups, alerts, dashboard). |
| `mtf_zone_strategy.pine` | `strategy()` running the same engine, with sizing, orders and an R-ledger stats table. |
| `tools/sync_engine.py` | Copies the engine block (between `ENGINE START/END` markers) from the indicator into the strategy. `--check` checks that both copies match. |

Pine cannot import a local file without publishing a library, so the engine is duplicated.
**Always edit the indicator copy, then run `python3 tools/sync_engine.py`.**

---

## 2. Timeframe ladder

`MTF: timeframe selection = Auto` uses this table. The chart timeframe maps to the **largest
row ≤ the chart timeframe** (e.g. 2m uses the 1m row, 2H uses the 1H row).

| Chart | LTF | HTF |
|---|---|---|
| 1m | off | 15m |
| 3m | 1m | 30m |
| 5m | 1m | 1H |
| 15m | 5m | 4H |
| 30m | 5m | 4H |
| 1H | 5m (input: 5m or 15m) | 1D |
| 4H | 1H | 1W |
| 1D and above | 4H | 1M |

These are configurable research defaults. They aren't claimed to be optimal.

**Edge cases**
- Non-standard or non-time charts (Renko, Range, Kagi, P&F, Line Break, Heikin Ashi, tick): MTF is
  **off**, and the dashboard shows a warning, because their OHLC is synthetic or not time-sliced.
- `Manual` mode: if the HTF is not strictly above the chart TF, or the LTF is not strictly below it,
  that layer is **disabled with a warning**. It is never silently swapped.
- A layer equal to the chart TF is never drawn twice.
- A disabled layer still requests the chart TF, so the request call stays valid, and its output is ignored.

---

## 3. Non-repainting design

| Layer | How it is fetched | When an event becomes usable |
|---|---|---|
| HTF (confirmed) | `request.security(tf, mtf_eventsConfirmed(), lookahead_on)`. Every element is offset `[1]` **inside** the requested context, because a tuple can't be history-indexed from outside. | On the first chart bar after the HTF bar **closes**. It is deduplicated by HTF bar time, so it is processed once. |
| HTF (developing) | `request.security(tf, mtf_events(), lookahead_off)` | Display only: hollow grey boxes on the last bar. **Never** used by setups, scoring or alerts. |
| Chart TF | direct call | On the bar's close. |
| LTF | `request.security_lower_tf(tf, mtf_events())`, which returns one array element per intrabar | Intrabars are processed in time order on the closed chart bar. Each intrabar is processed only once (`time > lastProcessed`). Chart bars with no intrabars are counted (dashboard: "LTF bars w/o intrabars"). This happens when history goes beyond TradingView's intrabar limit. |

All engine state changes happen **only when `barstate.isconfirmed`**: zone validity, zone
interaction, setups and the ledger. So realtime ticks can't create markers that later disappear.

**Pivot timing.** A swing printed by `ta.pivothigh/low(len, len)` is only *known* `len` bars after the
pivot. The engine draws it at the pivot bar (`pivotTime`), but creates it, and lets rules see it, only
on the confirmation bar (`confirmTime`). The same applies to OBs: `confirmTime` is the BOS bar, not
the OB candle.

---

## 4. Zone definitions (frozen across all models)

All thresholds below are inputs in the **MTF Zone Definitions** group. Changing one is a *new
experiment*, not a new model.

| Object | Definition |
|---|---|
| **ATR** | `ta.atr(14)` of the timeframe that detects the object. |
| **Displacement candle** | `abs(close - open) >= dispAtr × ATR[1]`. The ATR is measured *before* that candle. |
| **FVG (bull)** | `low > high[2]`, gap `>= fvgMinAtr × ATR`. Optionally, the middle candle is a bullish displacement candle measured with `ATR[2]`. Zone = `[high[2], low]`. Visual origin = candle 1. It is confirmed at candle 3's close. Bear FVG is the mirror. |
| **OB (bull)** | The last down-close candle before a bullish displacement candle becomes a candidate. It becomes an OB only if a **BOS** (close above the last unbroken confirmed swing high) happens within `obBosBars` bars of the displacement. Zone = that candle's `[low, high]`. `confirmTime` = the BOS bar. `relVol` = that candle's volume ÷ its 20-bar SMA. Bear OB is the mirror. |
| **Swing H/L** | `ta.pivothigh/low(pivLen, pivLen)`. See *Pivot timing* above. A swing line is **taken** when price wicks through it. The line then freezes and turns dotted. |
| **Structure trend** | `+1` after a close above the last unbroken confirmed swing high, `-1` after a close below the last unbroken confirmed swing low. That swing is then consumed. This is BOS/CHoCH state. |
| **Dealing range** | The last confirmed swing high and low on the HTF. They are never consumed. EQ = midpoint. |
| **Discount / Premium** | Price below / above the HTF EQ. |
| **CE** | 50% of the zone's **original** boundaries. It is fixed at creation and never recomputed. |
| **OTE** | Longs: `rangeHigh − [0.62 … 0.79] × range`. Shorts: `rangeLow + [0.62 … 0.79] × range`. Both bounds are inputs. |
| **Liquidity sweep** | Long: `low` below the most recent **confirmed** chart-TF swing low and `close` back above it. Short: the mirror. |
| **EQH / EQL** | Two consecutive confirmed chart-TF swing highs (or lows) within `eqAtr × ATR` of each other and within `eqExpiry` bars. Level = the more extreme of the two. A wick through followed by a close back inside = **EQ sweep**, which consumes the level. A close through, or expiry, removes it. |
| **IFVG / Breaker** *(research toggle)* | When a zone is invalidated (body close through its far edge), it is replaced by an opposite-polarity zone with the same boundaries: an **IFVG** from an FVG, or a **Breaker** from an OB. `validity = Flipped`, active from the next bar. Price is inside it at creation, so its first *touch* is the retest. It is removed when closed through again. It does not flip twice. |

---

## 5. Three independent state machines

One machine never implies another.

### 5.1 Zone validity: *is the zone still a valid level?*
```
Active ──(body close beyond far edge)──▶ Invalidated   (removed)
Active ──(per-layer cap exceeded)──────▶ Dropped       (removed)
Invalidated ──(flip toggle on)─────────▶ new zone, validity = Flipped
```
Bull far edge = `bot`, so invalidation is `close < bot`. Bear: `close > top`. Wicks never invalidate.

### 5.2 Zone interaction: *what has price done with it?* (facts, not states)
| Field | Meaning |
|---|---|
| `touchCount` | Number of separate visits: price was outside, then traded into the zone. Being inside at creation is **not** a touch. |
| `firstTouchTime` | Time of the first visit. |
| `newTouch` | True on the bar a new visit starts. This is what arms a setup. |
| `ceTouched` | A bar's range has included the CE. |
| `deepestPen` | Deepest penetration as a fraction of zone height. Can exceed 1 (wick through). |
| `filled` | FVG/IFVG traded fully through by a wick. |

A touched, CE-hit or filled zone **stays valid**. The legacy chart-only FVG/OB sections, which
deleted zones on first touch or fill, are kept for comparison but default **off**.

### 5.3 Setup lifecycle: *one record per trade idea*
```
Armed ──T(trigger)──▶ Triggered ──next open──▶ Open ──▶ Closed (TP | SL | GapSL | TimeExit)
  │                      
  ├─ no trigger within window ─────────▶ Expired
  ├─ zone Invalidated / Dropped ───────▶ Cancelled
  └─ trigger, but filter / risk / busy ▶ Rejected (reason recorded)
```
- **Arming**: a `newTouch` on a valid HTF AOI zone, inside the research window (and the session,
  if the session filter is on). The zone must have no live setup, and `setupCount < maxSetupsPerZone`
  (default 1 = first-touch hypothesis).
- At most one non-terminal setup per zone. Zone invalidation **after** the fill does not close the
  trade; only the stop, target or time exit closes it.

---

## 6. Area of interest (context, not an entry)

- **AOI** = a valid HTF zone. In `HTF zone ∩ lower-TF zone` mode, the AOI is only the largest overlap
  with a valid same-direction chart-TF or LTF zone. If no overlap exists when the zone is touched,
  no setup is armed.
- On the chart an AOI is drawn as a **BUY ZONE / SELL ZONE** with its quality grade and setup
  status (§15). The 4 categories below describe the AOI → setup path:

| Cat. | Meaning | Role |
|---|---|---|
| **L** Location | Price is inside the AOI. Disc/Prem is shown next to it as information. | gate (arming) |
| **S** Structure | HTF structure trend = AOI direction. This is a single flag; chart-TF BOS is not counted a second time. | info (filter in models B+) |
| **T** Trigger | A setup on this AOI has triggered. | gate |
| **R** Risk | That setup passed the cost-adjusted risk gate (✗ = rejected for risk). | gate |

---

## 7. Trade rules (hypothesis H0)

| Rule | Definition (identical for every model) |
|---|---|
| Trigger **T0** | The first chart bar (the arming bar included) within `trigWin` bars that closes in the trade direction **and** beyond the prior bar's extreme. Long: `close > open and close > high[1]`. |
| Only the first T0 counts | If that T0 fails a filter or the risk gate, the setup is **Rejected**. It does not wait for a later bar. So every filtered model's trades are a **subset** of Model A's (with *One trade at a time* off). |
| Entry | Market order, next bar's **open**. |
| Stop | AOI far edge ∓ `stopBuf × ATR14`, measured at the trigger. |
| Target | `targetR × (triggerClose − stop)`, priced at the trigger. Realised R uses the actual fill. |
| Risk gate | `(targetR·risk − 2·cost) / (risk + 2·cost) >= minRR`, where `cost` = per-side spread/2 + slippage + commission. |
| Time exit | After `maxHold` bars in the trade, exit at the next bar's open. |
| One position | *One trade at a time* (default on) rejects triggers while busy. See §8 for why to turn it off for pure feature comparison. |
| Variant **T1** *(separate experiment)* | The first bar that trades through the AOI CE and closes back on the trade side. Never compare a T1 run to a T0 run as if it were a model step. |

---

## 8. Models: the ablation ladder

Every model shares the zone definitions, AOI definition, trigger, stop, target, sizing, costs,
session and window. Models differ **only** by which facts are required at trigger time. Each fact is
recorded on every setup, whether or not it is required.

| Filter | Test at trigger time | A | B | C | D | E | F |
|---|---|---|---|---|---|---|---|
| `Struct` | HTF structure trend == trade direction | – | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Sweep` | Chart-TF liquidity sweep in the trade direction within the last `sweepBars` bars (trigger bar included) | – | – | ✓ | ✓ | ✓ | ✓ |
| `PD` | Long in Discount / short in Premium of the HTF dealing range | – | – | – | ✓ | ✓ | ✓ |
| `Disp` | The trigger candle is a displacement candle | – | – | – | – | ✓ | ✓ |
| `CE` | The AOI's CE has been touched (by the trigger bar's close) | – | – | – | – | – | ✓ |

**Single-feature runs** `A+Struct`, `A+Sweep`, `A+PD`, `A+Disp`, `A+CE` add exactly one filter to the
baseline. The cumulative ladder confounds order: what D adds depends on what B and C already removed.
The single-feature runs measure each feature's marginal effect against the same baseline trades.

**Overlaps removed on purpose**
- The sweep is a filter, never part of the trigger.
- Displacement and CE are separate steps.
- OTE is excluded from the ladder because it overlaps P/D.
- EQ-sweep is excluded because it overlaps `Sweep`.
- IFVG/Breaker AOIs are excluded because they change the AOI set.

These are research toggles, each run as its own experiment against Model A.

**One trade at a time.** With it **on**, models are path-dependent: a model that removes trade X may
then take trade Y, which X would have blocked. For the clean feature comparison, turn it **off**. The
R ledger then books every trigger independently, so model trades are exact subsets. The strategy can
only execute while flat; the stats table counts the skipped triggers.

---

## 9. Costs and fills

`strategy()` cost arguments must be compile-time constants (`input.*()` is not allowed there).
The declaration sets defaults, and **Settings → Properties overrides them**:

| Property | Default | Notes |
|---|---|---|
| Commission | 0.01% per side (`strategy.commission.percent`) | Percent is used instead of cash-per-contract because a per-contract cash value would misprice FX/CFD unit quantities. For futures, switch Properties to *per contract* with your broker's fee. |
| Slippage | 2 ticks | Applies to market and stop fills, not to limit (TP) fills. |
| Order timing | `process_orders_on_close = false` | Market entry at the next bar's open. |
| Fill model | `fill_orders_on_standard_ohlc = true`, `calc_on_every_tick = false`, `use_bar_magnifier = true` | The bar magnifier only takes effect on plans that support it. |
| Pyramiding / margin | 0 / margin checks off | One position. Sizing never triggers margin calls. |

**Set the same numbers in the "MTF Costs (ledger)" inputs**, because Pine cannot read Properties.

Suggested starting values (replace them with your broker's numbers):

| Market | Commission | Slippage | Spread input |
|---|---|---|---|
| Index / metal futures | per contract (e.g. 2.0 per side) | 1–2 ticks | 0 (already in the traded price) |
| FX / CFD (e.g. EURUSD, XAUUSD) | 0–0.005% | 1–2 ticks | your typical spread in ticks |
| Crypto spot / perps | 0.04–0.1% | 1–5 ticks | 0–2 ticks |

**Spread.** TradingView backtests have no bid/ask. Market fill prices can't be shifted in code, so
spread is modelled in the **R ledger** (half the spread charged on each side). For the tester's
equity curve, add the spread to the Properties slippage.

**Same-bar stop and target.** When one bar touches both, the intrabar path is unknown. The R ledger
counts it as a **loss** and reports how many trades were ambiguous. TradingView's emulator guesses
the path instead, so the two can differ on these trades.

**Gaps.** A gap through the stop fills at the open (≈ −1R or worse). A gap through the target fills at
the open (the better price), matching the emulator.

**Sizing (strategy only).** `qty = equity × risk% / ((|entry − stop| + 2·cost) × pointvalue)`,
rounded down to the *Quantity step*. All primary metrics are in **R**, so they do not depend on size.
A trigger whose size rounds to 0 is booked by the ledger, skipped by the tester, and counted.

---

## 10. Metrics and logs

Stats table (strategy, top-right), all in net R:
- trades, win rate, expectancy, profit factor, total R, max drawdown (R), average hold
- average MAE / MFE (R)
- number of ambiguous bars
- funnel: armed → expired / cancelled / rejected (filter, risk, busy)
- tester skips
- expectancy split by each fact (✓ vs ✗). Run under Model A to see each feature's raw effect.
- expectancy split by session (NY time: London 02–08, NY AM 08–12, NY PM 12–17, Asia/Other)
- TradingView tester trades / net profit, as a cross-check

**Event log.** Every terminal setup writes one CSV line to **Pine Logs** (both scripts):
```
SETUP,id,dir,state,reason,zone,trigTime,entry,stop,target,exit,R,holdBars,MAE_R,MFE_R,ambiguous,fStruct,fSweep,fPD,fDisp,fCE,session,grade,period
```
Filter Pine Logs by `SETUP,`, export the lines, and analyse them offline (e.g. pandas: bootstrap
confidence intervals on expectancy, results by regime, per-feature logistic regression).

---

## 11. Research protocol

1. **Fix the experiment.** Pick the symbol(s), chart TF, zone definitions, AOI mode, trigger, stop,
   target, costs and session. Write them down.
2. **Design on in-sample only.** Set *Research window = In-sample* and choose the split date. Tune
   *only* here, and as little as possible.
3. **Run the ladder on in-sample.** Run A–F and the five `A+X` runs with *One trade at a time = off*.
   Record trades, expectancy, PF, max DD and the ambiguous count.
4. **Freeze, then run out-of-sample once.** Set *Research window = Out-of-sample* and repeat step 3
   **without changing anything**. Compare **expectancy, drawdown and trade count, not win rate**.
5. **Execution check.** Re-run the chosen model with *One trade at a time = on* and compare the
   tester's numbers to the ledger's.
6. **Robustness.** Change one thing at a time: costs ×2, another symbol, an adjacent TF, ± one step on
   each frozen threshold. An edge that disappears under small changes is not an edge.
7. Treat research toggles (OTE, EQ-sweep, RelVol, IFVG/Breaker AOIs, T1) as **separate experiments
   against Model A**, following the same IS → OOS discipline.

Small samples are noise. With fewer than ~100 OOS trades, treat any difference between models as
unproven.

---

## 12. Verification tests

**Repaint test** (run it on 5m, 15m and 1H):
1. Open Bar Replay well inside history and step forward bar by bar for 50–100 bars.
2. Take screenshots of the HTF zones, AOIs, ▲/▼ markers and the stats table at a few points.
3. Exit replay and reload the chart. Zones, markers and R results on those bars must be **identical**.

**Cross-TF consistency.** Put the indicator on a 5m and a 15m chart with the same manual HTF (e.g.
1H). The same 1H zone must show the same top/bottom and origin time on both charts.

**Sync check.** Run `python3 tools/sync_engine.py --check`. It must print "already in sync".

---

## 13. First-release checklist

- [ ] Compiles in the TradingView Pine Editor (indicator and strategy).
- [ ] Displays confirmed HTF, chart-TF and LTF zones without duplicates.
- [ ] Zone prices and times match across chart timeframes (cross-TF test).
- [ ] Zone creation, interaction, invalidation and flips are deterministic (repaint test).
- [ ] No future-confirmed pivots or unclosed HTF data reach signals (repaint test, §3).
- [ ] Buy/Sell setups are reproducible, with explicit entry, stop, target and expiry.
- [ ] Alerts fire once per setup ID.
- [ ] Backtest results with realistic costs, ledger vs tester cross-checked.
- [ ] Each feature's out-of-sample marginal effect measured (A+X runs) and recorded.

---

## 14. Known limitations

- Not compile-tested here. Expect to fix a few syntax lines in the Pine Editor.
- The developing-HTF layer only shows a still-forming bar in realtime. On a closed market it shows the
  most recent HTF bar that has not yet been processed.
- `request.security_lower_tf` has an intrabar history limit, so early chart history has no LTF layer.
  Those bars are counted.
- Volume (`relVol`) is tick volume on most FX/CFD feeds. It is a feature to test, not evidence of
  institutional activity.
- The R ledger and TradingView's tester can differ on ambiguous bars, on trades whose size rounds to
  0, and on spread handling. The ledger is the primary metric.

---

## 15. Buy/Sell Zones: display modes, quality grade, setup status, results

Three separate things are shown for each zone, and they are never mixed:

| | Question it answers | Source |
|---|---|---|
| **Quality grade** (A+ / A / B) | How good is the *context* right now? | 4 checks below, recomputed each closed bar |
| **Setup status** | Is there an actual trade? | Setup lifecycle (§5.3) |
| **Results** | How did past setups *of this grade* end, under these exact settings? | R ledger (§9–10) |

### 15.1 Quality grade
Each valid HTF zone, i.e. each AOI candidate, gets 4 checks. Every check uses only values known on
the current closed bar.

| Check | Buy zone passes when (Sell = mirror) |
|---|---|
| Overlap | A valid bullish chart-TF or LTF OB/FVG overlaps the zone now. |
| Trend | HTF structure trend is up now. |
| Location | The zone midpoint is in Discount of the current HTF dealing range. |
| Zone sweep | A bullish sweep (wick below the latest confirmed chart-TF swing low, close back above) whose wick reached **into this zone, or within `sweepTol × ATR` below it**. It must come after the zone was confirmed and within the last `sweepBars` bars. A sweep elsewhere on the chart doesn't count. |

**A+** = 4/4, **A** = 3/4, **B** = ≤ 2/4.
- A zone ahead of price is typically **A**. It becomes A+ when price sweeps liquidity into it.
- The grade can go up or down from bar to bar. Past bars are never revised.
- The grade describes context. It is **not** a probability.

### 15.2 Setup status
| Status | Meaning |
|---|---|
| Waiting | No setup on this zone yet. |
| Armed | Price came back into the zone; waiting for the trigger. |
| In trade | Triggered (entry next open) or open. |
| Traded | The zone's setup has closed. |
| Expired / Rejected | The touch produced no trade: no trigger in the window, or it failed a filter, the risk gate, or a position was already open. |

### 15.3 Results per grade
- **Population**: setups closed by the engine on *this chart load*. That fixes the symbol, chart TF,
  model, trigger, stop/target/time exit and ledger costs to the current settings. Nothing from other
  settings is pooled. The configuration is shown as `Config` in the dashboard.
- **Grade attribution**: the zone's grade on the setup's **trigger bar**.
- **Win rate** = winning closed trades ÷ all closed trades of that grade, rounded to a whole %.
  **Avg R** = mean net R per closed trade, costs included. **n** = number of closed trades.
  Open, expired, rejected and cancelled setups are excluded. A bar touching both stop and target is a loss.
- **In-sample / out-of-sample**: trades are split by trigger time against the *IS / OOS split* date.
  Labels show **out-of-sample** stats once there are ≥ 20 OOS trades; otherwise in-sample stats are
  shown and marked `in-sample`. Fewer than 20 trades is marked `low sample`. OOS figures are only
  out-of-sample if no rule or setting was tuned on data after the split date.
- `won 61% of 38` means 23 of 38 past trades won. It does **not** mean the next trade has a 61% chance.
- The indicator and strategy run the same engine block, so trigger times and outcomes match.
  TradingView's tester can still differ on ambiguous bars (§9).

### 15.4 Display modes (drawings only)
| Element | Clean (default) | Standard | Full |
|---|---|---|---|
| Buy/Sell Zones with grade ≥ *Show zones with quality grade ≥* (default A) | nearest *N* per side (default 2) | nearest *N* per side | all graded zones, incl. B |
| ▲/▼ markers, stop/target lines | setups with a shown grade | same | all setups |
| Raw HTF zones and swings | – | ✓ | ✓ |
| Chart-TF / LTF zones and swings, developing HTF, EQ lines | – | – | ✓ |
| Premium/Discount, OTE | – | ✓ | ✓ |
| Legacy sections (VP, S/D, BOS/CHoCH, CISD, SMT, Kill Zones, legacy FVG/OB, LRL) | – | – | each behind its own toggle |
| Dashboard | compact | MTF rows | legacy + MTF rows |

- Gates act where objects are **created**, so hidden objects are never created.
- **Merging** is display-only: overlapping zones with the same direction and the same grade are drawn as
  one box listing its members. Setups and stats stay attributed to each individual zone.
- **Ranking**: distance from the close to the zone's nearest edge. A zone price is inside ranks first (distance 0).
- **Touch highlight**: a stronger fill while price is in the zone, based on closed-bar state only.
- **Grade diagnostics** (any mode) adds the 4 checks to each label, e.g. `Overlap ✓ Trend ✓ Discount ✗ Sweep ✓`.
- Zones, grades, setups, the ledger and Strategy Tester results are identical in every mode.

### 15.5 Grade as a trading filter (separate experiment)
In the strategy, *Research: trade only grade ≥* is `All` by default. Setting it to `A` or `A+` is an
experiment **outside** the A–F ladder: the grade already contains Struct, P/D and a sweep, so
combining it with models B–F double-counts them. Compare it against Model A with `All`, IS → OOS.

### 15.6 Release checklist (Buy/Sell Zones)
**Grading**
- [ ] A+ requires all 4 checks; A requires 3.
- [ ] A sweep counts only for the zone and direction it belongs to.
- [ ] Grades use only information available at that bar.

**Performance**
- [ ] Win rate and avg R come from closed trades under the defined exit rules, with costs.
- [ ] Stats are limited to the current symbol / TF / model / rules / costs, and the config is shown.
- [ ] IS and OOS are clearly separated and labelled.

**Display**
- [ ] Clean shows only eligible zones and relevant trade markers.
- [ ] Standard and Full reveal detail without changing trading decisions.
- [ ] Merging and nearest-zone selection preserve zone identity and correct ranking.

**Reliability**
- [ ] COT is safely disabled for unsupported symbols (default off; the library is only reached on futures or with a manual CFTC code).
- [ ] Indicator and strategy agree on signal timestamps and outcomes.
- [ ] Changing display mode leaves Strategy Tester results unchanged.
