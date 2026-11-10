# Crypto Research Terminal

A terminal workspace for testing short-term crypto price forecasts against live
market data, simple baselines, and execution costs.

The current focus is **research in shadow mode**: a frozen, fitted micro-price
estimator records predictions while later prices arrive. It places no exchange
orders. The earlier paper-trading baseline is paused; its history is retained.

## What it does

- Records public Kraken spot quotes and trades in SQLite.
- Displays price, spread, imbalance, feed freshness, and worker health.
- Compares midpoint, weighted midpoint, and a fitted Stoikov-style estimate.
- Measures prospective prediction error at 3, 15, and 60 seconds.
- Runs offline CatBoost experiments with chronological splits, purged labels,
  simple baselines, feature ablations, and fee/delay scenarios.
- Preserves paper positions, simulated fills, account state, and entry controls.

The recorder, research worker, and viewer run separately. Closing the viewer
leaves the other processes running. Local processes require an awake computer;
24/7 hosting is not implemented.

## Quick start

Python 3.9 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
```

Run each command in a separate terminal from the project folder:

```sh
.venv/bin/quant collect
```

```sh
.venv/bin/quant shadow
```

```sh
.venv/bin/quant watch
```

Shadow calibration requires historical quotes with enough supported transitions.
If calibration reports insufficient data, let the recorder collect more data,
then retry. The first model is frozen; subsequent starts reuse it. An existing
viewer must be restarted to load code updates. Ctrl+C closes the current process.

Public data needs no exchange account or API keys. Use one recorder and one
shadow worker per database. The default pair is BTC/USD and the default database
is `data/live.sqlite3`.

### Offline interface demo

```sh
.venv/bin/quant collect --demo --seconds 120
.venv/bin/quant watch --db data/demo.sqlite3
```

Synthetic data is explicitly labeled and is not evidence of trading performance.
`--demo` also selects the separate demo database for paper/research workers.

### Offline model experiments

```sh
.venv/bin/python -m pip install '.[research]'
.venv/bin/quant research
```

Results under `data/research/` include a frozen database snapshot, implementation
copy, development features, out-of-fold predictions, model files, parameters and
fingerprints. The final time block is unscored. Repeated development experiments
are not a substitute for an untouched prospective test.

### Original paper baseline

`quant paper` runs the original unvalidated long-only imbalance baseline. Existing
paused accounts remain paused. A new database starts with $100 simulated cash,
$10 entry notional, a 60-second hold, 0.5-second execution delay, and hypothetical
40-bps fees per side. These are experiment assumptions, not verified exchange
fees or published optimal settings. New entries are blocked after a $3 loss
relative to initial equity. This is not a guaranteed maximum loss.

The worker models ask entries and bid exits on post-delay quotes, checks displayed
size, and retains positions during stale feeds. Stopping it stops position
management until restarted. It has no real-money execution integration.

## Research basis and limits

The fitted estimator is an independent adaptation of
[Stoikov's micro-price research](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2970694).
Its event-time horizon is six price moves, not a fixed number of seconds.
Our fixed-clock scores investigate transfer across horizons. Initial checks on
the author's samples were mixed; no profitable edge has been established.

| Document | Contents |
|---|---|
| [Micro-price shadow mode](docs/MICROPRICE_SHADOW.md) | Equations, adaptations, sample results, live operation |
| [Literature selection](docs/LITERATURE_SELECTION.md) | Source credibility and research selection |
| [Reproduction audit](docs/REPRODUCTION_AUDIT.md) | CatBoost adaptation and evaluation protocol |
| [Research notes](RESEARCH.md) | Project questions and implementation history |

The feature named `microprice_offset_bps` in the first CatBoost experiment is a
weighted-midpoint offset, not the fitted state-transition estimator. This naming
is retained in historical artifacts for reproducibility.

## Checks

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Tests cover delayed fills, fees, restart recovery, stale-data handling, paused
entries, model recursion, prospective forecasts, feature causality, split purging,
trade deduplication, and execution diagnostics.

## Data and reproducibility

`data/`, virtual environments, logs, and credentials are excluded from Git.
Market recordings and downloaded reference datasets are local artifacts, not
redistributed with this repository. Reference download hashes are recorded
locally. Check source licensing before redistributing third-party code or data.

The collector retries disconnections but cannot recover missing events. There
is no automatic retention limit; monitor disk usage. Receipt time is a local
clock measurement, not exchange or execution latency. Simulation does not model
market impact or actual exchange acknowledgements. No statistical significance,
profitability, or production-readiness claim is made.

## Model-driven paper trading and charts

A separate diagnostic account can run alongside shadow research:

```sh
.venv/bin/quant model-paper
.venv/bin/quant watch
```

Run the worker and viewer separately, with `collect` and `shadow` also running.
The default viewer now shows simulated positions, a price chart with buy/sell
markers, an equity chart after costs, and recent fills. Charts use a three-minute
time axis and do not interpolate across missing buckets. Full research view:

```sh
.venv/bin/quant watch --view research
```

The account is `data/model-paper.sqlite3`; research remains in `data/live.sqlite3`.
The worker reads the latest source quote and the frozen model without writing
research forecasts or scores. It records no retrospective trades.

This is an **unvalidated execution diagnostic**, not a profitable strategy claim.
It buys when the fitted estimate is above the current ask, uses a $100 simulated balance, up to $10 entry notional, a 15-second hold,
0.5-second delay and 40-bps hypothetical fees per side. It is deliberately not
cost-gated: weak signals may produce trades that predictably lose after fees.
The UI displays signal size next to assumed round-trip fees. These are explicit
experimental choices, not optimal settings from the paper. No leverage is used.

Displayed quantity must cover the whole fill. The existing account-level loss
limit blocks new entries after a $3 loss and manages an open exit. It cannot
guarantee maximum loss. Pending positions/fills and configuration survive
restarts; stopping the worker pauses management. Different model IDs or settings
require a different account database. `--demo` uses separate demo source/account
files; pass the matching `--account-db` to the viewer.

## Interactive terminal redesign

`quant watch` now opens the Textual cockpit: a dark, responsive layout with a
large price plot, equity plot, execution state, scrollable fills, and tabs.
The interface opens the databases read-only and never starts/stops workers or
changes strategy/account settings.

| Key | Action |
|---|---|
| `1`, `2`, `3` | Trading, Research, Logs |
| Left / Right | 3-, 15-, or 30-minute chart window |
| `A` | Toggle the rotating ambient trefoil |
| `Q` | Close the viewer only |

The trefoil is a small 3D parametric knot rendered with Braille characters. It
is purely decorative; rotation, shading and speed do not represent performance,
prediction confidence, or connection status. Disable it with `--no-animation`.
Braille chart strokes provide sub-character resolution. Actual appearance
varies with terminal/font support. Time gaps over five seconds are not connected.

Use `quant watch --classic` for the original Rich viewer. `--once` still prints
a static classic frame for inspection. Changes to the interface require
restarting the viewer; trading and research workers continue separately.

Themes follow the selected Textual theme rather than fixed dark colors. Press
Ctrl+P, search for `theme`, and select a theme. The selection is saved locally
beside the market database in `ui-preferences.json` and restored next time.
Charts, animation and status colors follow that selection too. This does not
change the terminal application's global profile or trading configuration.

The animation panel has three purely decorative options: Trefoil,
Orbitals, and Wave lattice. Click its `◀` / `▶` buttons to cycle, or left/right
click the artwork to advance. The selected option is saved with the theme in
local display preferences. `A` still pauses/resumes motion.

The animation uses the original larger panel size, with thicker Braille strokes
and a continuous depth-based color gradient. It avoids switching between dots
and solid blocks, which can create patchy surfaces during rotation.
