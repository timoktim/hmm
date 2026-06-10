# CODEX_STAGE03V_WP0.5_sample_feasibility_preflight

Repository: timoktim/hmm

Index id: `STAGE03V-WP0.5-v1`

Work package: `docs/work_packages/stage03v/STAGE03V_WP0.5_sample_feasibility_preflight.md`

Suggested branch: `stage03v/wp0.5-sample-feasibility-preflight`

## Instruction

Start from updated `main`. Confirm PR74 / Stage03V WP0 has been merged and that `docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md` records WP0 as accepted or at least contains the WP0 contracts and ledger artifacts. Create the suggested branch and execute only `STAGE03V-WP0.5-v1`.

This package is a sample-feasibility preflight. It counts evidence and emits feasibility verdicts before any target dataset construction or modeling work.

## Read first

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
docs/work_packages/stage03v/STAGE03V_WP0.5_sample_feasibility_preflight.md
configs/risk_event_signal_contract_v1.yaml
configs/readiness_policy_risk_event_v1.yaml
configs/stage03v_sw_l2_universe_manifest_v1.yaml
reports/stage04/prospective_validation_ledger.stage03v.template.jsonl
```

## Required work

Implement a Stage03V sample feasibility module, CLI, gate script, tests, and reports.

Create:

```text
src/evaluation/stage03v_sample_feasibility.py
scripts/stage03v_sample_feasibility_gate.sh
tests/test_stage03v_sample_feasibility.py
reports/stage03v/sample_feasibility_report.md
reports/stage03v/sample_feasibility_report.json
```

Update:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
```

The execution index should mark WP0 as archived / accepted and WP0.5 as active or accepted depending on the branch state. WP1 and later packages must remain blocked.

## CLI requirement

Implement:

```bash
python -m src.evaluation.stage03v_sample_feasibility \
  --db data/db/a_share_hmm.duckdb \
  --output reports/stage03v/sample_feasibility_report.md \
  --summary-json reports/stage03v/sample_feasibility_report.json \
  --no-fetch
```

`--no-fetch` must be default. The module must never call data updaters or external network APIs.

If the DB is unavailable, emit a partial report and JSON summary. Do not crash.

If required SW2021 L2 tables are unavailable, emit partial / blocked evidence. Do not invent rows.

If the benchmark is unavailable, emit `benchmark_target_unavailable` and compute market blocks from cross-sectional event-share only.

## Core calculations

Use pure Python / pandas helper functions so tests can run on synthetic data without DuckDB.

Implement or equivalent:

```text
compute_mae_events(frame, horizons, thresholds, cutoff_date)
compute_market_event_blocks(events, event_share_thresholds, horizon)
compute_idiosyncratic_episodes(events, market_blocks, horizon)
compute_effective_event_evidence(market_blocks, idiosyncratic_episodes, discounts)
assign_feasibility_verdict(row)
build_sample_feasibility_report(...)
```

Target definition:

```text
path_return_i(t, k) = C_i(t+k) / C_i(t) - 1
MAE_i(t, N) = min_{1 <= k <= N} path_return_i(t, k)
downside_event_i(t, N, X) = 1{ MAE_i(t, N) <= -X }
```

Core horizons:

```text
N in {5, 10, 20}
```

Diagnostic horizons:

```text
N in {1, 3}
```

Fixed thresholds:

```text
X in {0.03, 0.05, 0.08, 0.10}
```

Recommended first-readiness mapping to report explicitly:

```text
5d:  3% and 5%
10d: 5% and 8%
20d: 8% and 10%
```

Preliminary volatility-scaled threshold feasibility may be computed only if causal ex-ante volatility can be estimated safely:

```text
X = k * ex_ante_vol_N, k in {1.0, 1.5, 2.0}
```

If not safe or not available, report `vol_scaled_feasibility_status=deferred_to_wp3_5` with reasons. Do not block fixed-threshold feasibility on this.

## Cross-cutoff censoring

For historical-development feasibility counting:

```text
trade_date <= 2026-06-10
target_observation_end_date <= 2026-06-10
```

If `target_observation_end_date > 2026-06-10`, the row must be excluded from development feasibility counts or counted separately as `cross_cutoff_censored`. It must not be labeled using post-cutoff prices.

Report:

```text
cross_cutoff_censored_count
cross_cutoff_excluded_count
historical_development_labeled_count
historical_development_unlabeled_due_to_cutoff_count
```

## Market event blocks

For each horizon × threshold × target kind:

```text
compute cross-sectional event_share by trade_date
mark event-active dates at event_share >= 10%, >= 20%, and >= 30%
use 20% as primary market-block threshold unless report recommends a documented change
also mark benchmark downside event dates when pre-registered benchmark target is available
merge contiguous active dates
merge gaps <= horizon
count merged blocks as market_event_block_count
```

Report:

```text
market_event_block_count_10pct
market_event_block_count_20pct
market_event_block_count_30pct
primary_market_event_block_count
benchmark_event_count
benchmark_target_status
```

## Idiosyncratic industry episodes

For each industry × horizon × threshold × target kind:

```text
find continuous industry event days
merge gaps <= horizon
remove or mark portions overlapping primary 20% market event blocks
count remaining non-overlapping episodes as idiosyncratic_industry_episode_count
```

Effective evidence:

```text
idiosyncratic_discount_sensitivity = [0.10, 0.25, 0.50]
discounted_idiosyncratic_episode_count = discount * idiosyncratic_industry_episode_count
effective_event_evidence_count = primary_market_event_block_count + discounted_idiosyncratic_episode_count
```

Report all three discount sensitivities.

## Feasibility verdicts

Emit per horizon × threshold × threshold_type × target_kind:

```text
eligible
diagnostic_only
defer_threshold
drop_threshold
blocked_short_history
partial_missing_data
```

Default gating:

```text
market_event_block_count < 2: usable_probability forbidden, even if idiosyncratic episodes exist
effective_event_evidence_count < 5: blocked or drop_threshold
5 <= effective_event_evidence_count < 10: diagnostic_only or ordinal_only maximum
effective_event_evidence_count >= 10: eligible for modeling, but not automatically usable_probability
```

Do not assign `usable_probability` in WP0.5.

## SW2021 coverage checks

Check and report when local DB tables support it:

```text
taxonomy_provider
taxonomy_version
taxonomy_level
industry_count_total
industry_count_after_quality_filter
min_trade_date
max_trade_date
coverage_start
coverage_end
history_continuity_status
reform_window_continuity_status
silent_entity_break_count
duplicate_entity_count
short_history_entity_count
quality_filter_exclusion_count
constituent_count_filter_status
```

If constituent snapshots are unavailable, report `constituent_count_filter_status=not_applicable_missing_constituents`.

SW2021 L1 aggregation may be diagnostic only. Do not promote it as the empirical universe.

## Tests

Create `tests/test_stage03v_sample_feasibility.py`.

Minimum coverage:

```text
MAE event labels correct on simple price paths.
Off-by-one semantics use t+1 through t+N.
Cross-cutoff rows are censored or excluded and never labeled from post-cutoff prices.
Market blocks merge contiguous active dates.
Market blocks merge gaps <= horizon.
10/20/30 event-share sensitivity counts differ correctly.
Industry-specific events outside market blocks count as idiosyncratic episodes.
Industry events overlapping market blocks are not double-counted.
Effective evidence uses discount sensitivities 0.10 / 0.25 / 0.50.
Low-evidence slices receive expected feasibility verdicts.
Missing DB path produces a partial report without crashing.
No external data fetch is attempted.
```

## Required commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_sample_feasibility.py
python -m src.evaluation.stage03v_sample_feasibility \
  --db data/db/a_share_hmm.duckdb \
  --output reports/stage03v/sample_feasibility_report.md \
  --summary-json reports/stage03v/sample_feasibility_report.json \
  --no-fetch
pytest -q -m "not slow"
git diff --check
```

If local DB is unavailable, the CLI should still emit a partial report. Synthetic tests remain acceptance-critical.

## Forbidden behavior

Do not create persistent target dataset tables.

Do not commit DuckDB, WAL, local cache, or full data extracts.

Do not train any model.

Do not calibrate probabilities.

Do not assign readiness or `usable_probability`.

Do not consume prospective final holdout evidence.

Do not backfill cross-cutoff historical-development labels.

Do not fetch external data.

Do not modify HMM / HSMM training algorithms.

Do not implement Stage03V2 or Stage03V3.

Do not create UI, trading, buy/sell, sizing, or decision outputs.

## Return format

Use the work package return contract exactly:

```text
index_id: STAGE03V-WP0.5-v1
branch: stage03v/wp0.5-sample-feasibility-preflight
PR: ...
status: pass / partial / fail

commands run:
- ...

results:
- ...

files changed:
- ...

DB used: yes/no
DB path: ...
V7 coverage available: yes/no/unknown
SW2021 L2 universe coverage: pass/partial/missing
benchmark target status: available/unavailable
cross-cutoff censoring enforced: yes/no
market event-block sensitivity reported: yes/no
idiosyncratic episodes reported: yes/no
effective evidence counts reported: yes/no
eligible slice count: ...
diagnostic-only slice count: ...
deferred/dropped slice count: ...

external data fetch: no
target dataset built: no
model training: no
probability calibration: no
readiness assigned: no
holdout consumed: no
HMM/HSMM training modified: no
Stage03V2 implemented: no
Stage03V3 implemented: no

remaining risks:
- ...
```
