# CODEX_STAGE03V_FIX1_contract_repairs

Repository: timoktim/hmm

Index id: STAGE03V-FIX1-v1

Work package: `docs/work_packages/stage03v/STAGE03V_FIX1_contract_repairs.md`

Suggested branch: `stage03v/fix1-contract-repairs`

## Instruction

Start from updated `main`. Read the work package and the audit context it
references. Execute only `STAGE03V-FIX1-v1`.

Your task is to close six contract-compliance gaps in the Stage03V evaluation
code: (F1) validation-fold market-event-block hard ban for
`usable_probability_candidate`; (F2) Brier-retention-versus-identity ban;
(F3) date-aware sample weighting in the logistic hazard fit, or an explicit
in-contract waiver; (F4) hard-block report status on any nonzero
holdout-consumption counter; (F5) forced `metrics = None` and
`event_label = None` in the cross-cutoff censoring branch; (F6) record the
implemented calibration-split semantics in the signal contract.

This is a code-and-tests package. Do not re-run WP0.5-WP6 pipelines. Do not
regenerate any `reports/stage03v/` evidence artifact. Do not modify or
regenerate `reports/stage03v/purge_embargo_fold_plan.json`. Do not change
target definitions, horizons, thresholds, or the fixed-threshold mainline. Do
not train new model families. Do not consume or inspect prospective final
holdout data (`trade_date >= 2026-06-11`). Do not fetch external data. Do not
create UI, decision, trading, buy/sell, or sizing outputs.

## Required tests

Each fix needs a synthetic test that fails without the fix and passes with it:

```text
tests/test_stage03v_fix1_market_block_ban.py
tests/test_stage03v_fix1_brier_retention.py
tests/test_stage03v_fix1_date_weighting.py
tests/test_stage03v_fix1_holdout_hard_block.py
extend tests/test_stage03v_path_targets.py
extend tests/test_stage03v_contracts.py
```

## Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_fix1_market_block_ban.py tests/test_stage03v_fix1_brier_retention.py tests/test_stage03v_fix1_date_weighting.py tests/test_stage03v_fix1_holdout_hard_block.py
pytest -q tests/test_stage03v_path_targets.py tests/test_stage03v_contracts.py
pytest -q -m "not slow"
git diff --stat -- reports/   # must be empty
```

If the full not-slow suite fails for unrelated pre-existing reasons, document
the failure and still return the FIX1-specific test results.

## Return format

Use the return contract in the work package. Include the PR link, commands
run, created/updated file list, which of F1-F6 were closed versus waived, and
explicit yes/no flags for:

```text
external data fetch
empirical pipeline rerun
fold plan modified
reports regenerated
holdout consumed
HMM/HSMM training modified
decision or trading output
```
