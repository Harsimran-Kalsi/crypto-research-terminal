# Paper audit and adaptation protocol

Reference: Bieganowski and Ślepaczuk, *Explainable Patterns in Cryptocurrency
Microstructure*, arXiv:2602.00776v1.
https://arxiv.org/html/2602.00776v1
Audit date: November 9, 2026.

## What the source establishes

The paper studies three-second midpoint log returns using Binance perpetual
futures quotes and trades. It uses CatBoost and chronological validation with
purging. Feature families include top-of-book imbalance, spread, trade flow,
and VWAP-to-mid deviations. Its execution section adjusts positions on signal
changes, rather than imposing our existing 60-second hold. Latency is not modeled.

Sections 4–5 discuss both GMADL and squared-error objectives; section 4 also says
models are trained with squared error and selected with GMADL. This requires
clarification before claiming an exact objective reproduction. Exact rolling
windows, complete feature equations, tuned parameter values and fee settings
are not sufficiently specified for a bit-for-bit reproduction here.

No author-linked implementation or downloadable original dataset was verified
in the article or the author's GitHub profile during this audit. Search surfaced
`amazingchow/epcm`, a third-party implementation; it was not treated as author
code and no code was copied from it. This is a search limitation, not proof that
an author release does not exist.

## Our implementation: adaptation v1

This is an independently implemented, paper-inspired **spot adaptation**, not a
replication of reported results and not a validated trading strategy. The
existing imbalance paper worker remains a separate unvalidated mechanics demo.
This research command never updates that account or deploys a model to it.

The choices below are ours, fixed before inspecting the experiment results.

- Source: recorded Kraken BTC/USD spot data, selected explicitly by symbol and
  live/synthetic prefix. Take a consistent read-only SQLite snapshot first.
- Clock: local receipt timestamps; exchange timestamps remain in raw records.
  We make no claims about network latency or exchange-time alignment.
- Quotes: one-second decision grid, taking the last quote received by each grid
  time. Reject ages over five seconds. Split on session changes or quote gaps
  over five seconds. Require a 30-second trailing history after each boundary.
- Trades: update messages only; exclude historical subscription snapshots;
  deduplicate by symbol/trade ID. Audit sequence gaps and invalid values. Block
  model evaluation if that audit fails. No missing trade is inferred as zero.
  Trade-channel failure without detectable ID gaps is still a limitation.
- All trailing trade windows are `(t-10, t]`, using local receipt time. Burst
  receipts are treated as bursts; original exchange-time ordering isn't inferred.
- Missing buy/sell VWAPs are filled with zero relative deviation plus explicit
  presence indicators. This convention is ours and is exposed to the model.
- Labels: `10,000 * log(mid(t+h)/mid(t))`, h = 3, 15, 60 seconds. Only complete
  labels inside one contiguous segment are retained. Quote ages remain capped.
  We use a common row set across horizons for paired comparison.

### Feature definitions

| Feature | Definition |
|---|---|
| imbalance | `(bid_qty-ask_qty)/(bid_qty+ask_qty)` |
| spread_bps | `10,000*(ask-bid)/mid` |
| microprice_offset_bps | `10,000*((ask*bid_qty+bid*ask_qty)/(bid_qty+ask_qty)/mid-1)` |
| momentum_5s_bps | `10,000*log(mid(t)/mid(t-5))` |
| volatility_30s_bps | Population standard deviation of thirty one-second midpoint log changes in bps |
| signed_volume_10s | Sum of buy quantity minus sell quantity in the trailing window |
| trade_imbalance_10s | `(buy_qty-sell_qty)/(buy_qty+sell_qty)`, zero if neither occurs |
| buy/sell_vwap_offset_bps | `10,000*(side VWAP/mid-1)`, zero if absent |
| buy/sell_present | 1 if that side has positive traded quantity, else 0 |

### Fixed model and evaluation protocol

- Final 20% of the elapsed sample time is reserved and unscored. No final test
  metrics or predictions are exported. Never treat repeatedly inspected
  development folds as an untouched test. As new data arrives, the split changes;
  freeze a dataset fingerprint before any confirmatory study.
- Three expanding-window development folds. Every training label ends strictly
  before validation starts. Every validation label ends before its fold ends.
  A conservative 60-second purge applies at every horizon.
- Models: zero-return, training-mean, price-only CatBoost (spread, momentum,
  volatility), full-feature CatBoost. Each CatBoost fit uses 200 iterations,
  depth 4, learning rate .03, L2 regularization 5, seed 42, RMSE, two CPU threads.
  No tuning, early stopping against validation, GMADL selection, or SHAP claims.
- Minimum 100 training and 30 validation rows per fold are smoke-test thresholds,
  not statistical sufficiency. Even overlapping rows in a long capture are not
  independent observations. Report MSE, nonzero-return direction accuracy, and
  zero-return fraction; make no p-value or significance claims.
- Compare full features against price-only on identical dates. This ablation
  jointly removes quantity and flow features; it does not isolate one feature's
  causal contribution.
- Independent long-only execution diagnostics use positive forecasts exceeding
  current spread plus twice the assumed fee. Fixed $10 notional, no overlapping
  trades within a scenario, ask entries and bid exits. Require displayed sizes
  to cover the entire quantity. These trials are not a full portfolio backtest.
- Fee scenarios: 0, 10, 40, 80 bps per side. Delay scenarios: 0, .5, 1 second
  on entry and exit. These are assumptions, not verified exchange fee tiers.
  Hold from entry fill for the forecast horizon, then apply exit delay.
  Use first subsequent quotes, cap arrival tolerance at five seconds, reject
  quote gaps over five seconds and do not cross validation boundaries.
- Delisting unfillable trials can bias diagnostics; skipped counts are exported.
  No market impact, extra slippage, partial fills or exchange acknowledgements
  are modeled. Scenario results do not guarantee executable performance.

## Outputs and next decisions

`quant research` produces a content-addressed directory containing the report,
source/data fingerprint, a frozen SQLite snapshot and implementation copy,
parameters, exact package versions, development features,
out-of-fold predictions and fitted development models. Identical runs reuse the
existing report rather than overwrite it. Models are research artifacts only.

Before deployment: freeze a longer dataset, audit channel health, independently
review features and fills, assess dependent-sample uncertainty, confirm applicable
fees, and run a frozen prospective model in shadow mode. Collect multiple days
and regimes before interpreting findings; a short capture is only an integration
check. A negative economic result is a valid research outcome.
