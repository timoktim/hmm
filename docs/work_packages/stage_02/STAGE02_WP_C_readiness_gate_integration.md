# STAGE02_WP_C_readiness_gate_integration

Stage: 02 / Causal evidence and reproducible validation gates
Work package: WP-C
Index ID: STAGE02-WP-C-v1
Executor: Codex C
Recommended branch: `stage02/wp-c-readiness-gate-integration`

## Objective

Build one conservative readiness decision layer for HMM outputs. It should combine Stage 01 diagnostics, the Stage 02 causal cache audit, and CI validation status into a single reportable result.

This is an integration package. It must not train models, fetch market data, change HMM or HSMM training, or promote HMM output to trading advice.

## Dependency order

Preferred order:

1. Merge STAGE02-WP-A causal cache audit.
2. Merge STAGE02-WP-B CI validation artifact skeleton.
3. Start this package from updated `main`.

Do not start this package from old `main` if the causal cache audit file is absent.

## Starting point

```bash
git fetch origin
git checkout main
git pull --ff-only
git checkout -b stage02/wp-c-readiness-gate-integration
```

Read first:

```text
docs/runtime/LOCAL_DB_HANDOFF.md
docs/acceptance/stage_01/STAGE01_FINAL_INTEGRATION_SUMMARY.md
reports/stage01_integration/stage01_integration_summary.json
reports/causal_cache/stage02_wp_a_causal_cache_audit.json
```

## Allowed files

Add:

```text
src/evaluation/readiness_gate.py
tests/test_readiness_gate.py
reports/readiness_gate/stage02_wp_c_readiness_gate_report.md
reports/readiness_gate/stage02_wp_c_readiness_gate_report.json
```

Small updates allowed only if needed:

```text
src/ui/readiness_policy.py
src/ui/causal_boundary.py
src/ui/evidence_badges.py
```

Do not modify:

```text
src/models/
src/features/
src/evaluation/hmm_confidence.py
src/evaluation/hmm_label_alignment.py
src/evaluation/hmm_churn_dwell.py
src/evaluation/causal_cache_audit.py
```

## Gate inputs

Use what is available and report missing inputs clearly:

```text
model_evidence_registry
validation_runs
hmm_confidence_run_summary
hmm_label_alignment_audit
hmm_churn_dwell_run_summary
causal cache audit report or table
CI validation report or docs
```

## Gate output

Create a `ReadinessGateDecision` with:

```text
run_id
status
evidence_level
readiness_status
display_action
state_confidence_status
label_identity_status
churn_dwell_status
causal_cache_status
ci_validation_status
reasons
warnings
required_next_evidence
```

Use only canonical readiness values:

```text
blocked
research_only
internal_only
partial
validated
decision_ready
```

This package should be conservative. Given current Stage 01 risks, expected output is likely `research_only` or `partial`, not `validated`.

## Decision rules

Minimum rules:

- Missing DB means no data-backed readiness pass.
- Missing causal cache audit keeps output at research-only level.
- Causal cache unavailable keeps output at research-only level.
- High label ambiguity keeps state identity interpretation conservative.
- Missing or weak confidence keeps output conservative.
- Excessive churn downgrades display action.
- Missing CI validation is a tracked risk.
- Any evidence boundary violation should make the gate fail safely.

Do not emit `decision_ready` in this package.

## CLI

```bash
python -m src.evaluation.readiness_gate \
  --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" \
  --run-id latest \
  --output reports/readiness_gate/stage02_wp_c_readiness_gate_report.md \
  --summary-json reports/readiness_gate/stage02_wp_c_readiness_gate_report.json \
  --no-fetch
```

## Tests

Cover:

- missing inputs degrade conservatively;
- unavailable causal cache blocks stronger readiness;
- high label ambiguity blocks stronger state identity claim;
- no decision-ready output;
- invalid readiness values rejected;
- CLI writes Markdown and JSON;
- no external data fetch.

Commands:

```bash
python -m compileall -q src tests
pytest -q tests/test_readiness_gate.py
pytest -q tests/test_ui_readiness_policy.py tests/test_ui_causal_boundary.py
pytest -q -m "not slow"
python -m src.evaluation.readiness_gate --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" --run-id latest --output reports/readiness_gate/stage02_wp_c_readiness_gate_report.md --summary-json reports/readiness_gate/stage02_wp_c_readiness_gate_report.json --no-fetch
```

## Acceptance criteria

Pass if:

- readiness output is deterministic and conservative;
- current tracked risks are preserved;
- report explains which evidence prevents stronger readiness;
- no external data fetch;
- no model training change;
- no DuckDB or WAL commit;
- tests pass.

## Return format

```text
WP: STAGE02-WP-C-v1
status: pass / partial / fail
branch: stage02/wp-c-readiness-gate-integration
PR: ...
commands run:
- ...
local DB:
- path used: ...
- preflight: pass/fail
readiness gate:
- run_id: ...
- readiness_status: ...
- display_action: ...
- reasons: ...
- warnings: ...
inputs:
- confidence: available/missing
- label_alignment: available/missing
- churn_dwell: available/missing
- causal_cache: available/missing/unavailable
- CI validation: available/missing
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```
