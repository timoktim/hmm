#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
PYTEST_BIN="${PYTEST_BIN:-.venv/bin/pytest}"
DB_PATH="${STAGE03V_V7_DB:-data/db/a_share_hmm_tushare_v7.duckdb}"

echo "STAGE03V_RERUN1_B2_GATE_DB=$DB_PATH"

"$PYTHON_BIN" -m compileall -q src tests
"$PYTEST_BIN" -q tests/test_stage03v_downshift_experiment.py
"$PYTHON_BIN" -m src.evaluation.stage03v_downshift_experiment \
  --db "$DB_PATH" \
  --target-support reports/stage03v/risk_event_target_support.json \
  --logistic-hazard reports/stage03v/logistic_hazard_report.json \
  --calibration-readiness reports/stage03v/calibration_readiness_report.json \
  --readiness-matrix reports/stage03v/downside_readiness_matrix.csv \
  --baseline-slice-metrics reports/stage03v/baseline_diagnostics_slice_metrics.csv \
  --fold-plan reports/stage03v/purge_embargo_fold_plan_v2.json \
  --trial-accounting reports/stage03v/validation_trial_accounting.json \
  --output reports/stage03v/downshift_experiment_report.md \
  --summary-json reports/stage03v/downshift_experiment_report.json \
  --arm-metrics reports/stage03v/downshift_experiment_arm_metrics.csv \
  --daily-exposure-sample reports/stage03v/downshift_experiment_daily_exposure_sample.csv \
  --bootstrap-iterations 300 \
  --no-fetch
"$PYTHON_BIN" -m json.tool reports/stage03v/downshift_experiment_report.json >/dev/null

"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("reports/stage03v/downshift_experiment_report.json").read_text(encoding="utf-8"))
print(
    "STAGE03V_RERUN1_B2_GATE="
    f"{report.get('status')} "
    f"db={report.get('source_db_path')} "
    f"candidate_slices={report.get('candidate_slice_count')} "
    f"scored_slices={report.get('scored_candidate_slice_count')} "
    f"entity_days={report.get('validation_entity_day_count')} "
    f"holdout_scores={report.get('prospective_holdout_score_count')} "
    "report=reports/stage03v/downshift_experiment_report.md "
    "summary_json=reports/stage03v/downshift_experiment_report.json "
    "no_fetch=yes research_only=yes"
)
raise SystemExit(0 if report.get("status") == "pass" else 1)
PY
