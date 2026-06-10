# STAGE03V_WP0.5_sample_feasibility_preflight

Stage: 03V / Volatility and downside-risk hazard

Work package: WP0.5

Index id: `STAGE03V-WP0.5-v1`

Suggested branch: `stage03v/wp0.5-sample-feasibility-preflight`

Codex instruction: `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP0.5_sample_feasibility_preflight.md`

Date: 2026-06-10

## Objective

Run a sample-feasibility preflight before target-dataset construction. This package determines which downside-risk horizons, thresholds, and threshold types have enough effective event evidence to justify later target building and modeling.

WP0.5 is an evidence-counting and feasibility package only. It must not train models, calibrate probabilities, assign readiness, create a target dataset table, consume prospective final holdout evidence, or implement Stage03V2 / Stage03V3.

## Route anchors

Use:

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
configs/risk_event_signal_contract_v1.yaml
configs/readiness_policy_risk_event_v1.yaml
configs/stage03v_sw_l2_universe_manifest_v1.yaml
reports/stage04/prospective_validation_ledger.stage03v.template.jsonl
```

## Stage boundary

Allowed:

- Read local DuckDB data if available.
- Inspect SW2021 L2 industry OHLCV coverage.
- Inspect broad A-share benchmark OHLCV coverage.
- Compute preliminary path-event labels in memory or temporary report data frames for feasibility counting.
- Compute event base rates, market event blocks, idiosyncratic industry episodes, and effective event evidence counts.
- Emit feasibility verdicts per horizon / threshold / threshold type / target kind.
- Create deterministic unit tests using synthetic data.
- Generate Markdown and JSON feasibility reports.

Forbidden:

- Do not create persistent `risk_event_target_dataset_v1` tables.
- Do not commit local DuckDB files, WAL files, or full local data extracts.
- Do not train logistic hazard, volatility baseline, HAR diagnostic, calibration, readiness matrix, or validation models.
- Do not mark any slice `usable_probability`.
- Do not consume or inspect prospective final holdout performance.
- Do not use post-2026-06-10 data for historical-development feasibility labels, except to mark or demonstrate censoring behavior.
- Do not backfill cross-cutoff historical-development labels.
- Do not fetch external data.
- Do not modify HMM or HSMM training algorithms.
- Do not create UI, trading, buy/sell, sizing, or decision outputs.

## Required deliverables

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

The index should mark WP0 as archived / accepted and WP0.5 as active or accepted depending on the branch state. Later packages remain blocked.

## Required CLI

Implement a CLI:

```bash
python -m src.evaluation.stage03v_sample_feasibility \
  --db data/db/a_share_hmm.duckdb \
  --output reports/stage03v/sample_feasibility_report.md \
  --summary-json reports/stage03v/sample_feasibility_report.json \
  --no-fetch
```

Required behavior:

- `--no-fetch` must be default behavior.
- If the DB is unavailable, emit a partial report with `status=partial_missing_db` or equivalent and do not crash.
- If required SW2021 L2 industry tables are unavailable, emit `blocked_short_history` or `partial_missing_universe` evidence rather than inventing rows.
- If the benchmark is unavailable, emit `benchmark_target_unavailable` and compute market blocks from cross-sectional event-share only.
- The CLI must not require private DuckDB in CI. Unit tests must run on synthetic temporary data.

## Input contracts

Read the WP0 contracts and enforce their key values:

```text
stage_id: stage03v
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
empirical universe: SW2021 L2 industry only
benchmark target: broad_a_share_downside_event using MAE
cross_cutoff_censoring_policy: permanent
```

If contracts are missing or inconsistent, the report must return `status=blocked_contract_missing` or equivalent.

## Feasibility targets

Use the primary Stage03V1 target definition:

```text
path_return_i(t, k) = C_i(t+k) / C_i(t) - 1
MAE_i(t, N) = min_{1 <= k <= N} path_return_i(t, k)
downside_event_i(t, N, X) = 1{ MAE_i(t, N) <= -X }
```

Core horizons:

```text
N in {5, 10, 20}
```

Optional diagnostic horizons:

```text
N in {1, 3}
```

Candidate fixed thresholds:

```text
X in {0.03, 0.05, 0.08, 0.10}
```

Recommended first-readiness mapping to report explicitly:

```text
5d:  3% and 5%
10d: 5% and 8%
20d: 8% and 10%
```

Also compute preliminary volatility-scaled threshold feasibility if causal ex-ante volatility can be estimated safely:

```text
X = k * ex_ante_vol_N, k in {1.0, 1.5, 2.0}
```

If ex-ante volatility cannot be computed safely in WP0.5, report `vol_scaled_feasibility_status=deferred_to_wp3_5` with reasons. Do not block fixed-threshold feasibility on this.

## Permanent cross-cutoff censoring in WP0.5

For all historical-development feasibility counting:

```text
trade_date <= 2026-06-10
target_observation_end_date <= 2026-06-10
```

If `target_observation_end_date > 2026-06-10`, the row must be excluded from development feasibility counts or counted separately as `cross_cutoff_censored`. It must not be labeled with post-cutoff prices.

Report fields must include:

```text
cross_cutoff_censored_count
cross_cutoff_excluded_count
historical_development_labeled_count
historical_development_unlabeled_due_to_cutoff_count
```

## Market event-block rule

For each horizon × threshold × target kind:

```text
compute cross-sectional event_share by trade_date
mark event-active dates at event_share >= 10%, >= 20%, and >= 30%
use 20% as the primary market-block threshold unless report recommends a documented change
also mark benchmark downside event dates when the pre-registered benchmark target is available
merge contiguous active dates
merge gaps <= horizon to avoid counting one selloff as many independent events
count merged blocks as market_event_block_count
```

Required output fields:

```text
market_event_block_count_10pct
market_event_block_count_20pct
market_event_block_count_30pct
primary_market_event_block_count
benchmark_event_count
benchmark_target_status
```

## Idiosyncratic industry episode rule

For each industry × horizon × threshold × target kind:

```text
find continuous industry event days
merge gaps <= horizon
remove or mark portions overlapping primary 20% market event blocks
count remaining non-overlapping episodes as idiosyncratic_industry_episode_count
treat different industries and non-overlapping periods as partially independent, not fully row-independent
```

Default effective evidence rule:

```text
market_event_block_count = primary 20% market-block count
idiosyncratic_discount = 0.25 by default
idiosyncratic_discount_sensitivity = [0.10, 0.25, 0.50]
discounted_idiosyncratic_episode_count = idiosyncratic_discount * idiosyncratic_industry_episode_count
effective_event_evidence_count = market_event_block_count + discounted_idiosyncratic_episode_count
```

Required output fields:

```text
idiosyncratic_industry_episode_count
discounted_idiosyncratic_episode_count_0_10
discounted_idiosyncratic_episode_count_0_25
discounted_idiosyncratic_episode_count_0_50
effective_event_evidence_count_0_10
effective_event_evidence_count_0_25
effective_event_evidence_count_0_50
```

## Default feasibility verdicts

For each horizon × threshold × threshold_type × target_kind, emit one of:

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

WP0.5 does not assign `usable_probability`. It only records whether a slice is eligible for later modeling.

## Long-horizon note

The report must include this interpretation note:

```text
The gap <= horizon merge rule intentionally makes long-horizon event blocks coarser.
For 20d horizons, a chain of selloff days across a quarter may count as one block.
This is a conservative effective-sample rule, not a data defect.
```

## SW2021 taxonomy and universe coverage checks

Check and report:

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
```

If constituent snapshots are unavailable, report `constituent_count_filter_status=not_applicable_missing_constituents`; do not invent constituent counts.

The empirical universe remains SW2021 L2 only. SW2021 L1 aggregation may be reported as diagnostic cross-check only and must not become the v1 empirical promotion universe.

## Suggested implementation approach

Use pure Python / pandas functions for the core calculations so tests can run on synthetic data without DuckDB.

Suggested functions:

```text
compute_mae_events(frame, horizons, thresholds, cutoff_date)
compute_market_event_blocks(events, event_share_thresholds, horizon)
compute_idiosyncratic_episodes(events, market_blocks, horizon)
compute_effective_event_evidence(market_blocks, idiosyncratic_episodes, discounts)
assign_feasibility_verdict(row)
build_sample_feasibility_report(...)
```

The CLI may have adapter code that reads actual local tables when available.

## Tests

Add `tests/test_stage03v_sample_feasibility.py`.

Minimum synthetic test coverage:

- MAE event labels are correct for simple price paths.
- Off-by-one semantics use `t+1` through `t+N`, not `t`.
- Cross-cutoff rows are censored or excluded and never labeled from post-cutoff prices.
- Market blocks merge contiguous active dates.
- Market blocks merge gaps `<= horizon`.
- 10% / 20% / 30% event-share sensitivity counts differ correctly.
- Industry-specific events outside market blocks count as idiosyncratic episodes.
- Industry events overlapping market blocks are removed or marked so they do not double-count.
- Effective evidence uses discount sensitivities 0.10 / 0.25 / 0.50.
- Slices below thresholds receive the expected feasibility verdict.
- Missing DB path produces a partial report without crashing.
- No external data fetch is attempted.

## Suggested commands

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

If the local DB is unavailable, the CLI command may return a partial non-crashing report. The synthetic unit tests remain the acceptance-critical tests.

## Reports

Generate:

```text
reports/stage03v/sample_feasibility_report.md
reports/stage03v/sample_feasibility_report.json
```

The report must include:

- index id;
- contract paths used;
- DB path and DB availability;
- external data fetch: no;
- source database coverage if available;
- SW2021 L2 universe coverage;
- taxonomy and quality-filter status;
- cross-cutoff censoring counts;
- candidate horizon / threshold grid;
- fixed-threshold feasibility matrix;
- preliminary volatility-scaled feasibility status;
- market-block counts at 10% / 20% / 30%;
- benchmark target status;
- idiosyncratic episode counts;
- effective evidence counts under all discount sensitivities;
- recommended eligible slices;
- recommended diagnostic-only slices;
- recommended deferred / dropped slices;
- long-horizon block-merge note;
- boundary flags.

Boundary flags must include:

```text
external_data_fetch: no
target_dataset_built: no
model_training: no
probability_calibration: no
readiness_assigned: no
holdout_consumed: no
HMM_HSMM_training_modified: no
stage03v2_implemented: no
stage03v3_implemented: no
```

## Acceptance criteria

WP0.5 passes if:

- Synthetic feasibility tests pass.
- The CLI emits a report and JSON summary without fetching data.
- Missing DB produces a partial report rather than a crash.
- If V7 local DB is available, source coverage and SW2021 L2 coverage are reported.
- Cross-cutoff target windows are censored or excluded from historical-development counts.
- Market event-block counts and 10/20/30 sensitivity are reported.
- Idiosyncratic industry episodes outside market blocks are reported.
- Effective evidence counts use discount sensitivity 0.10 / 0.25 / 0.50.
- Feasibility verdicts are emitted per candidate slice.
- No slice is assigned `usable_probability`.
- No target dataset table is created.
- No model is trained.
- No holdout is consumed.
- No external data is fetched.
- Stage03V2 and Stage03V3 remain unimplemented.

## Return format

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
