# Literature and author credibility audit

Checked November 9, 2026. This audit changes the recommended research anchor;
it does not change or deploy the running paper strategy.

## Existing authors

Robert Ślepaczuk has a verified relevant academic role: University of Warsaw
lists him as Associate Professor and Head of the Department of Quantitative
Finance and Machine Learning. His research includes econometrics, volatility
and algorithmic investment systems. This is relevant experience, not a guarantee
that any particular empirical finding will reproduce.
Source: https://www.wne.uw.edu.pl/en/members/profile/view/41

The department lists M.A. Bartosz Bieganowski as a PhD student. Search also finds
a Warsaw mathematician with the same name working on differential equations;
his credentials must not be attributed to the finance author without evidence.
Source: https://www.wne.uw.edu.pl/en/faculty/structure/departments/quantitative-finance

The selected 2026 article is verified on arXiv. This audit did not verify a
journal publication, independent reproduction, or author-linked code/data for
that particular paper. This does not establish their absence. Citation counts
from aggregators were not used as a credibility score.
Source: https://arxiv.org/abs/2602.00776

## Recommended foundation and comparison set

### Primary reproducibility anchor: Stoikov (2018)

*The micro-price: a high-frequency estimator of future prices*, Quantitative
Finance 18(12), 1959–1966, DOI 10.1080/14697688.2018.1489139.
https://www.tandfonline.com/doi/abs/10.1080/14697688.2018.1489139

The paper compares a fitted micro-price with midpoint and weighted-midpoint
predictors. Its author-posted working-paper page directly links the author's
notebook and sample data, making the starting experiment inspectable.
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2970694
https://github.com/sstoikov/microprice

The repository includes BAC and CVX quote CSVs from March 2011 and a notebook.
It is an old research artifact, not a maintained live-trading package. Public
visibility alone does not establish unrestricted redistribution permission;
check licensing before copying or redistributing any source or datasets.

Stoikov's Cornell academic page documents financial-engineering research roles.
https://people.orie.cornell.edu/sfs33/personal.html

### Predictive baseline: Gould and Bonart

*Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book*.
https://arxiv.org/abs/1512.03492

Fits logistic models for the direction of the next midpoint move in ten Nasdaq
stocks, with stronger results for large-tick stocks. Suitable for testing
queue-imbalance prediction. One-tick/event-time prediction must not be described
as evidence for a sixty-second profitable strategy.

### Mechanism: Cont, Kukanov and Stoikov (2014)

*The Price Impact of Order Book Events*, Journal of Financial Econometrics
12(1), 47–88. https://arxiv.org/abs/1011.6402

Studies the relation between order-flow imbalance and price changes over short
intervals. Explaining contemporaneous changes is different from predicting
future returns. OFI from successive quote events is also different from static
queue-size imbalance or signed executed volume.

Cont's Oxford profile documents a chair in mathematical finance and research
awards, including the Louis Bachelier Prize. The credentials support subject
expertise; they do not remove the need to test a new venue and horizon.
https://www.st-hughs.ox.ac.uk/people/professor-rama-cont/

### Modern comparison: Bieganowski and Ślepaczuk (2026)

Keep the existing CatBoost spot adaptation as a modern nonlinear comparator.
Its reproduction limitations are documented in REPRODUCTION_AUDIT.md. It should
not be the sole authority for the project or for deployed risk settings.

## Recommendation and experiment story

Anchor the next reproduction in Stoikov's inspectable estimator, with
queue-imbalance logistic regression as a simple predictive baseline. Use the
Cont–Kukanov–Stoikov work to explain the mechanism, then compare the current
CatBoost model on exactly the same prospective crypto sample.

Proposed original question: Does an estimator calibrated on quote transitions
retain useful information on a different venue and at 3/15/60-second horizons,
and how much survives fees, delay and changes in tick/spread conditions?

First reproduce the reference estimator on the provided sample with explicit
metrics; then adapt to our crypto data using train-only calibration. A new
venue/horizon is an extension, not an exact replication. Model complexity must
earn its place against midpoint, weighted midpoint, and simple predictive
baselines on the same dates. None of these papers supplies universal stop-loss,
take-profit or position-sizing settings.

## Terminology correction for our current artifacts

The current feature named `microprice_offset_bps` is the opposite-queue-weighted
midpoint offset: `(ask*bid_qty + bid*ask_qty)/(bid_qty+ask_qty) - mid`, in bps.
It is not the fitted state-transition estimator in Stoikov's paper. Historical
artifact names are retained for reproducibility; future versions should name
this `weighted_mid_offset_bps` and add the fitted estimator separately.

No full Stoikov reproduction has been implemented yet. The recorder, terminal,
execution simulator and chronological evaluation remain reusable.
