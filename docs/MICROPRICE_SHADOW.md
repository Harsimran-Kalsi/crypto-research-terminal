# Fitted micro-price shadow mode

Implemented November 9, 2026. The cockpit now displays an independently
implemented Stoikov-style finite-state Markov estimator. It submits no paper or
real orders. The old imbalance account is paused and retained as history.

## Method and explicit differences

Reference method: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2970694
Author notebook and samples: https://github.com/sstoikov/microprice

We independently construct transition probabilities between spread/imbalance
states. No-price-change transitions form Q; price-changing transitions form R;
expected signed price increments form a reward vector r. Solve
`g1 = solve(I-Q, r)` and `B = solve(I-Q, R)`. The estimate is midpoint plus
`g1 + B*g1 + ... + B^5*g1`, rescaled from ticks to price units. Symmetrize
training transitions by reflecting imbalance states and reversing price moves.

Our discretization uses training-only symmetric quantile boundaries (six bins
and three spread states for crypto). The reference check uses ten bins, two
spread states and a one-cent tick. The live tick is approximated from the
minimum positive training spread: this is an explicit assumption, not exchange
instrument metadata. We retain all observed price changes, whereas the notebook
filters some large changes. Sparse states with fewer than ten training
transitions abstain. Unsupported spreads abstain. Non-absorbing/singular models
fail calibration explicitly. No smoothing or guaranteed convergence to an
infinite-horizon fair price is claimed.

Calibration uses last-observed quotes per receipt-time second and excludes
adjacent pairs crossing session boundaries or gaps over five seconds. Quantile
boundaries are frozen. Resuming shadow reuses the saved model; it never silently
recalibrates. Models are separate by symbol and synthetic/live data mode.

## Reference check

The author's two public sample CSVs were downloaded to ignored local
`data/reference/` with URL and SHA-256 records in `manifest.json`. They are not
vendored into distributable source. `quant microprice-reference` fits on the
first 80% of each sample and scores supported quotes in the final 20% against
a later midpoint at least three seconds away (maximum eight seconds). There is
no claim to match published numbers: this is our fixed-clock diagnostic of an
adapted implementation. As in the notebook's CSV loading, the first numeric
line is omitted; the source CSVs use carriage-return line endings.

Initial diagnostic MSE in bps squared:

| Sample | Scored | Midpoint | Weighted midpoint | Fitted estimator |
|---|---:|---:|---:|---:|
| BAC | 104211 | 1.718004 | 3.549158 | 4.662832 |
| CVX | 86951 | 0.847088 | 0.871865 | 0.839143 |

This mixed result does not validate profitability or establish a universal
forecast advantage. Samples overlap and errors are dependent. No significance
test or trading performance claim is made. The exact JSON output, sample hashes
and fitted state offsets are in `data/reference/method-check.json`.

## Live operation

```sh
.venv/bin/quant shadow
.venv/bin/quant watch
```

Run each in a separate terminal; `quant collect` must be running separately.
The viewer does not start or stop shadow. Closing the worker stops prospective
sampling, and its heartbeat becomes stale. Forecasts/outcomes remain in SQLite.

The model fits once on historical data and only records later fresh quotes,
at most once per receipt-time second. It records midpoint, weighted midpoint,
fitted estimate or an explicit abstention. It scores the first later quote at
3/15/60 seconds with a five-second arrival tolerance, excluding session changes
and gaps over five seconds. It does not backfill missing historical forecasts
when restarted. Unresolved forecasts older than 180 seconds are not recovered.

Six price moves are an event-time horizon, not three or sixty seconds. The
fixed-clock scores investigate horizon transfer; they are not automatically
calibrated return forecasts, confidence intervals, or entry signals. The live
panel explicitly labels CatBoost as offline rather than inventing predictions.
A fair comparison with CatBoost requires a common frozen dataset and protocol.

## Terminal transition

An existing viewer retains its old code until restarted: Ctrl+C, then run
`quant watch` again. The default panel now prioritizes shadow research. The old
paper account is compactly displayed as an archived baseline when flat and
paused. Persistent pause cancels new buys but still allows managed time exits.
During this migration the old running worker was blocked from new entries,
allowed to close its position, then stopped. Its account was not reset.
