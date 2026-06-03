# STAGE03R_WP0_scope_freeze_signal_contract

Stage: 03R / Hazard-first lifecycle validation
Work package: WP0
Index ID: STAGE03R-WP0
Executor: Codex Stage03R-WP0
Recommended branch: `stage03r/wp0-scope-freeze-signal-contract`

## Objective

Freeze Stage03R scope and create the lifecycle signal contract before any Duration Hazard model work begins.

This package converts the route adjustment into machine-readable policy artifacts. It must clearly separate:

- HMM regime context;
- HSMM lifecycle interpretation;
- Duration Hazard as future primary exit signal;
- hidden / gated probability fields;
- allowed UI exposure and future decision-engine inputs.

This package does not implement the hazard model, exit target dataset, BOCPD, decision engine, robust HMM, sticky HMM, or any new training algorithm.

## Starting point

Start from updated `main` after Stage03 preflight gate has passed via PR #38.

```bash
git fetch origin
git checkout main
git pull --ff-only
git checkout -b stage03r/wp0-scope-freeze-signal-contract
```

Read first:

```text
docs/roadmap/STAGE03R_ROUTE_ADJUSTMENT_20260603.md
docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md
docs/runtime/LOCAL_DB_HANDOFF.md
reports/stage03_preflight/preflight_verdict.md
reports/stage03_preflight/preflight_verdict.json
```

If the preflight verdict artifacts are missing from `main`, use PR #38 body as evidence and record a warning in the report. Do not block WP0 solely because the previous verdict report file has not been refreshed, but do not claim a new full gate run unless actually run.

## Scope

Allowed additions:

```text
docs/roadmap/stage03r_scope_freeze.md
configs/lifecycle_signal_contract_v1.yaml
configs/readiness_policy_lifecycle_v1.yaml
reports/stage03r/stage03r_wp0_scope_freeze_report.md
reports/stage03r/stage03r_wp0_scope_freeze_report.json
tests/test_stage03r_signal_contract.py
```

Allowed small updates:

```text
docs/indexes/WORK_PACKAGE_INDEX.md
docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md
.gitignore
```

Do not modify source code except for tests. If a tiny loader helper is needed, add it under tests or keep it in the test file. Production source changes are not required for WP0.

Do not modify:

```text
src/models/
src/evaluation/
src/backtest/
src/ui/
src/data_pipeline/
```

## Required contract content

### `configs/lifecycle_signal_contract_v1.yaml`

Must define field categories:

```text
display_safe
internal_diagnostic
calibration_required
hidden
future_hazard_input
forbidden_decision_input
```

Must classify at least these fields:

```text
hmm_state_label
hmm_state_confidence
hmm_state_entropy
hmm_posterior_margin
hsmm_state_age
hsmm_state_phase
hsmm_duration_percentile
hsmm_duration_percentile_status
hsmm_duration_tail_status
hsmm_exit_tendency_ordinal
hsmm_raw_p_exit_1d
hsmm_raw_p_exit_3d
hsmm_raw_p_exit_5d
hsmm_raw_p_exit_10d
hsmm_raw_p_exit_20d
hsmm_calibrated_p_exit_1d
hsmm_calibrated_p_exit_3d
hsmm_calibrated_p_exit_5d
hsmm_calibrated_p_exit_10d
hsmm_calibrated_p_exit_20d
hsmm_next_state_tendency
hazard_exit_tendency_ordinal
hazard_calibrated_probability
hazard_readiness_status
hazard_sample_support
hazard_fallback_reason
```

Minimum required classifications:

- HMM state label/confidence/entropy/margin: `display_safe` or `internal_diagnostic` depending on current policy.
- HSMM age/phase/duration profile: `display_safe`.
- HSMM ordinal exit tendency: `internal_diagnostic` by default.
- HSMM raw/calibrated numeric p_exit: `calibration_required` or `hidden`, never default decision input.
- Hazard ordinal tendency: `future_hazard_input`.
- Hazard calibrated probability: `future_hazard_input` only when readiness permits.
- Missing/invalid/insufficient sample probability fields: `hidden`.

### `configs/readiness_policy_lifecycle_v1.yaml`

Must define readiness statuses:

```text
display_safe
internal_only
calibration_required
hidden
usable_probability
ordinal_only
baseline_only
insufficient_sample
invalid
abstain
```

Must define allowed transitions / usage rules:

- `usable_probability` may appear only after calibration and validation pass.
- `ordinal_only` may show low/medium/high, not numeric probability.
- `insufficient_sample` must not be filled with pseudo-probability.
- `invalid` and `hidden` must not be shown as numeric signal.
- `abstain` is a valid output, not a failure.
- Future decision engine may consume readiness-approved hazard fields, not raw HSMM probabilities.

### `docs/roadmap/stage03r_scope_freeze.md`

Must include:

- route summary;
- current HMM responsibility;
- current HSMM responsibility;
- future Duration Hazard responsibility;
- explicitly frozen HSMM responsibilities;
- explicitly out-of-scope models for Stage03R v1;
- evidence boundary and UI boundary;
- pass/fail criteria for WP0.

### `reports/stage03r/stage03r_wp0_scope_freeze_report.*`

Markdown and JSON must include:

```text
status: pass / partial / fail
stage03_preflight_status: pass / unknown
route_anchor: docs/roadmap/STAGE03R_ROUTE_ADJUSTMENT_20260603.md
contract_files_created
hsmm_numeric_p_exit_default_decision_input: false
hazard_primary_lifecycle_exit_engine: planned
out_of_scope_models
commands_run
external_data_fetch: no
training_algorithm_modified: no
DuckDB_committed: no
```

## Tests

Add `tests/test_stage03r_signal_contract.py` covering:

1. Both YAML files parse.
2. Required top-level sections exist.
3. HSMM raw/calibrated numeric p_exit fields are not categorized as default decision inputs.
4. `insufficient_sample` and `invalid` do not allow numeric probability display.
5. Hazard fields are future inputs but require readiness.
6. `abstain` is allowed.
7. Stage03R v1 out-of-scope list includes competing-risks, BOCPD, robust HMM, sticky HMM, VAR-HSMM, deep switching state-space, and full decision engine.

Use only standard Python libraries or existing project dependencies. If PyYAML is unavailable, either use the existing dependency if present or keep YAML simple enough to parse with a safe fallback in tests. Do not add new dependency solely for this WP unless already allowed by current requirements.

## Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03r_signal_contract.py
bash scripts/check_no_private_paths.sh
bash scripts/validate_stage01_no_private_db.sh
```

If feasible:

```bash
bash scripts/stage03_preflight_gate.sh
```

Do not require local private DB.

## Acceptance criteria

Pass if:

- Stage03R route is frozen in docs;
- lifecycle signal contract exists and is machine-readable;
- readiness policy exists and is machine-readable;
- HSMM numeric p_exit is not a default decision input;
- Duration Hazard is recorded as planned primary lifecycle exit engine;
- Stage03R v1 out-of-scope models are explicitly listed;
- tests pass;
- no external data fetch;
- no training algorithm changes;
- no DuckDB/WAL commit.

## Return format

```text
WP: STAGE03R-WP0
status: pass / partial / fail
branch: stage03r/wp0-scope-freeze-signal-contract
PR: ...
commands run:
- ...
contract files:
- configs/lifecycle_signal_contract_v1.yaml: created yes/no
- configs/readiness_policy_lifecycle_v1.yaml: created yes/no
scope freeze:
- HSMM numeric p_exit default decision input: false/true
- Duration Hazard primary lifecycle exit engine: planned yes/no
- out-of-scope models listed: yes/no
stage03 preflight:
- gate evidence: PR #38 / report file / rerun
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```