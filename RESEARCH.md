# Research direction — proposal, November 6, 2026

## User priorities

Build a technically interesting, current research and engineering project suitable for discussion with quantitative trading or technology firms. The project story should connect a defensible hypothesis, existing literature, original experiments, realistic evaluation, and a continuously running system. Asset and strategy remain open. Hosting selection is deferred.

## Recommended question (not yet an agreed strategy)

Can order-flow features predict short-horizon crypto returns, and does selective trading retain economic value after fees, spread, and execution delay?

Potential extension: estimate when a model should abstain, rather than trade every prediction. Start with simple models, then compare boosted trees and calibrated confidence filters. Study approximately 10-second, 60-second, and 5-minute horizons, explicitly distinguishing prediction from executable profit. Exact horizons should be fixed before the main evaluation.

## Sources checked

- HftBacktest: https://github.com/nkaz001/hftbacktest — open-source tick replay, queue and latency models. Candidate research engine; venue compatibility must be checked.
- Replay limitations: https://hftbacktest.readthedocs.io/en/latest/order_fill.html — simulated orders do not alter historical market data; fills and market impact remain approximations.
- NautilusTrader: https://github.com/nautechsystems/nautilus_trader — candidate event-driven research/live engine. Current default-branch v2 documentation differs from stable v1; pin compatible code and documentation before adoption.
- Explainable Patterns in Cryptocurrency Microstructure (January 2026): https://arxiv.org/abs/2602.00776 — preprint studying cross-asset order-book/trade features, CatBoost, and execution. Its futures findings are not evidence of spot profitability. An accompanying author code repository was not verified.
- UQ-LOB (September 2026): https://arxiv.org/abs/2609.31491 — preprint on uncertainty-aware forecasts and selective prediction. Improved forecasting is not proof of net trading profits. An accompanying author code repository was not verified.
- The good, the bad, and latency (2025): https://www.tandfonline.com/doi/full/10.1080/14697688.2025.2515933 — execution delays and adverse selection in crypto taker orders.
- Deflated Sharpe Ratio (2014): https://davidhbailey.com/dhbpapers/deflated-sharpe.pdf — selection bias, multiple trials, and non-normal returns. Statistical diagnostics do not repair leakage or unrealistic fills.

## Proposed experiment

1. Audit accessible spot-market trade/quote/depth feeds, recording permissions, history availability, timestamps, sequence numbers, and data cost. Select venue only after this audit.
2. Collect immutable events and local receive timestamps; detect gaps and reconstruct the book reproducibly.
3. Compare no-trade and simple price-based baselines, a linear order-flow model, and boosted trees. Add confidence filtering only after baseline evaluation.
4. Use chronological walk-forward splits with label-overlap purging, train-only preprocessing, a recorded experiment budget, and an untouched final period.
5. Report forecast quality and calibration separately from net execution results. Include ablations, paired comparisons, block-based uncertainty estimates, turnover, drawdown, fill rates, and adverse selection.
6. Stress fees, delays, slippage, and queue assumptions. Do not assume a touched limit price implies a fill. Measure edge decay and break-even costs.
7. Freeze a version and run forward paper trading; compare observed behavior with replay predictions without silently retuning the frozen model.

## Deliverables

- Reproducible data and experiment manifests, pinned dependencies, and explicit limitations.
- Concise research report including negative results and feature-removal studies.
- Deterministic event replay and restart/reconnect tests.
- Terminal cockpit displaying forecasts, decision/abstention reasons, net results, and feed health.
- Documented risk controls: position/notional caps, no leverage initially, stale-feed entry block, persistent risk limits, and explicitly managed open positions during halts.

Success as a portfolio project is credible evidence and robust implementation. A profitable strategy or a recruiting outcome is not promised.

## Implemented adaptation v1

The audit and fixed protocol are in `docs/REPRODUCTION_AUDIT.md`.
`quant research` now builds receipt-time features, trains fixed-parameter CatBoost
models and price-only ablations, compares zero/training-mean baselines across
3/15/60-second labels, and runs explicit fee/delay diagnostics. It records a
consistent raw database snapshot, implementation, fingerprints, development
predictions and model artifacts. The final time block is unscored.

This is a paper-inspired adaptation. Original author code/data were not verified;
our feature windows and execution policy are explicit independent choices.
No research model has been connected to the paper-trading worker.

## Credibility audit and recommended research anchor

See `docs/LITERATURE_SELECTION.md` for verified author roles, publication and
code/data evidence, and the updated recommendation: Stoikov's published
micro-price estimator as the primary reproducibility anchor; Gould–Bonart
queue prediction and Cont–Kukanov–Stoikov price impact as foundations; the
2026 CatBoost adaptation as a modern comparator. This is a literature decision,
not a deployed strategy change. Our existing microprice-named feature is a
weighted midpoint, not the fitted Stoikov estimator.

## Live shadow integration

A fitted six-move state-transition estimator is now implemented and connected to
the terminal. See `docs/MICROPRICE_SHADOW.md` for adaptation details and mixed
reference-sample diagnostics. This is an independent method check, not a claim
of exact reproduction. The original imbalance account is paused and archived;
research forecasts are recorded prospectively with 3/15/60-second outcomes.
