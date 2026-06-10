# CODEX_STAGE03V_WP0_scope_freeze_contracts_ledger

Repository: timoktim/hmm

Index id: STAGE03V-WP0-v1

Work package: `docs/work_packages/stage03v/STAGE03V_WP0_scope_freeze_contracts_ledger.md`

Suggested branch: `stage03v/wp0-scope-freeze-contracts-ledger`

## Instruction

Start from updated `main`. Read the route anchor and the WP0 work package:

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
docs/work_packages/stage03v/STAGE03V_WP0_scope_freeze_contracts_ledger.md
```

Execute only `STAGE03V-WP0-v1`.

Your task is to freeze Stage03V scope and create machine-readable contracts, readiness policy, split-role or Stage04-ledger-compatible manifest, SW2021 L2 universe manifest, execution index, config-validation tests, and WP0 evidence reports.

Do not build target datasets. Do not train models. Do not calibrate probabilities. Do not consume or inspect prospective final holdout performance. Do not fetch external data. Do not modify HMM/HSMM training algorithms. Do not create UI, decision, trading, buy/sell, or sizing outputs.

## Required content

Ensure the WP0 artifacts explicitly include:

- `information_cutoff_date = 2026-06-10`.
- `holdout_start = 2026-06-11`.
- quarterly prospective holdout review cadence.
- holdout consumption counting.
- permanent cross-cutoff censoring, where historical-development labels with `target_observation_end_date > 2026-06-10` must remain censored or excluded and must never be backfilled after future prices arrive.
- benchmark downside target definition, defaulting to the broad A-share benchmark from `market_benchmark_ohlcv`, preferably CSI All Share / 中证全指 when available, using the same MAE, horizon, and threshold policy as the evaluated slice.
- SW2021 L2 taxonomy and universe quality filter.
- comparability break versus earlier roughly 465 mixed industry/concept board evidence.
- validation-fold-only evidence counts for WP5 `usable_probability` readiness.
- Stage03V2 and Stage03V3 as placeholders only.

## Required commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_contracts.py
pytest -q -m "not slow"
```

If the full not-slow suite fails for unrelated pre-existing reasons, document the failure and still return the WP0-specific test result.

## Return format

Use the return contract in the work package. Include the PR link, commands run, created/updated file list, and explicit yes/no flags for:

```text
external data fetch
target dataset built
model training
holdout consumed
HMM/HSMM training modified
decision or trading output
permanent cross-cutoff censoring present
benchmark downside target present
```
