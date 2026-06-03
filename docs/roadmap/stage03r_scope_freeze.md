# Stage03R Scope Freeze

Date: 2026-06-03
Index ID: STAGE03R-WP0
Route anchor: `docs/roadmap/STAGE03R_ROUTE_ADJUSTMENT_20260603.md`

## Route Summary

Stage03R starts only after the Stage03 preflight gate evidence recorded by PR #38. The route is hazard-first:

```text
HMM causal regime context
+ HSMM lifecycle interpretation layer
+ Duration Hazard as planned primary lifecycle exit engine
+ ordinal fallback or abstain when support is insufficient
+ calibration, readiness, and held-out validation before any decision surface
```

This freezes the previous direction of trying to promote broad HSMM numeric `p_exit` before hazard work. HSMM remains useful, but it is not the default lifecycle exit probability engine for Stage03R.

## HMM Current Responsibility

HMM remains the causal regime context layer. It may provide:

- walk-forward state paths;
- regime or display labels;
- state confidence;
- entropy and posterior margin diagnostics;
- state stability, churn, and label identity monitoring.

HMM must not be treated as:

- a standalone alpha generator;
- a direct trading signal;
- an unvalidated return prediction engine.

## HSMM Current Responsibility

HSMM is frozen as a lifecycle interpretation layer. It may provide:

- state age;
- early / mature / late phase;
- duration percentile and duration tail status;
- display-label episode history;
- ordinal exit tendency when readiness policy permits;
- next-state tendency as a realized-episode-supported description.

HSMM numeric `p_exit` is not a default decision input. Raw or calibrated HSMM numeric `p_exit` can only be exposed as a numeric probability when a readiness policy explicitly marks it `usable_probability`; otherwise it remains calibration-required, hidden, ordinal-only, or internal diagnostic.

## Duration Hazard Future Responsibility

Duration Hazard is the planned primary lifecycle exit engine for Stage03R. Future hazard packages may own:

- causal exit target dataset construction;
- age-conditioned and horizon-specific exit tendency;
- logistic hazard baseline;
- age-bucket empirical baseline;
- isotonic calibration on validation folds only;
- state x horizon x age bucket readiness matrix;
- sample support and fallback reason;
- ordinal fallback and abstain.

Hazard fields are future inputs. They are not decision-ready by default. A future decision engine may consume only readiness-approved hazard fields, not raw HSMM probabilities.

## Frozen HSMM Responsibilities

The following HSMM responsibilities are frozen during Stage03R v1:

- lifecycle UI interpretation fields;
- state age / phase / duration profile;
- duration tail and percentile status semantics;
- ordinal exit tendency as non-numeric low / medium / high context;
- realized-episode next-state tendency;
- hiding or downgrading numeric `p_exit` unless readiness allows numeric exposure.

The following HSMM responsibilities must not expand during Stage03R v1:

- generic numeric `p_exit` display;
- precise exit probability for every state x horizon;
- direct ranking, sizing, buy/sell, or trading decisions;
- fallback that converts undefined or insufficient-sample probability into usable numeric probability.

## Out Of Scope For Stage03R v1

Stage03R v1 explicitly does not implement or promote:

- competing-risks hazard;
- BOCPD;
- robust HMM;
- sticky HMM;
- VAR-HSMM;
- deep switching state-space;
- full decision engine.

These may be revisited only after the hazard-first route has a validated baseline, readiness matrix, and held-out risk protocol.

## UI Boundary

The UI may show display-safe lifecycle and regime context. It may show ordinal labels such as low / medium / high only when the readiness policy allows `ordinal_only` or stronger.

The UI must not show invalid, hidden, missing, or insufficient-sample probability as a numeric lifecycle signal. It must not imply decision readiness from HMM labels, HSMM age, HSMM phase, HSMM duration percentile, HSMM raw `p_exit`, or unvalidated calibrated `p_exit`.

## Evidence Boundary

Every future promotion claim must include:

- causal construction or explicit research-only status;
- calibration status;
- validation status;
- sample support;
- readiness status;
- fallback reason;
- final held-out discipline where applicable.

`abstain` is a legal output. It means the evidence is not strong enough for the requested signal granularity, not that the pipeline failed.

## WP0 Pass Conditions

WP0 passes when:

- `configs/lifecycle_signal_contract_v1.yaml` exists and is machine-readable;
- `configs/readiness_policy_lifecycle_v1.yaml` exists and is machine-readable;
- HSMM numeric `p_exit` is not a default decision input;
- Duration Hazard is recorded as the planned primary lifecycle exit engine;
- invalid, hidden, missing, and insufficient-sample probabilities cannot be shown as numeric signals;
- the Stage03R v1 out-of-scope model list is explicit;
- tests covering the signal contract pass;
- no external data fetch occurs;
- no HMM/HSMM training algorithm is modified;
- no DuckDB or WAL file is committed.

## WP0 Fail Conditions

WP0 fails if any of the following happen:

- HSMM raw or calibrated numeric `p_exit` is promoted as a default decision input;
- Duration Hazard is implemented rather than scoped as planned future work;
- exit target dataset construction is started;
- BOCPD, robust HMM, sticky HMM, VAR-HSMM, deep switching state-space, competing-risks hazard, or a full decision engine is implemented;
- invalid or insufficient-sample probability can be displayed as numeric probability;
- production source code is modified outside the allowed WP0 scope;
- external data is fetched;
- DuckDB or WAL files are committed.
