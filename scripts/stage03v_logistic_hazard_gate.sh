#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
PYTEST_BIN="${PYTEST_BIN:-.venv/bin/pytest}"
DB_PATH="${STAGE03V_V7_DB:-data/db/a_share_hmm_tushare_v7.duckdb}"
FOLD_PLAN="${STAGE03V_FOLD_PLAN:-reports/stage03v/purge_embargo_fold_plan.json}"

echo "STAGE03V_LOGISTIC_HAZARD_GATE_DB=$DB_PATH"
echo "STAGE03V_LOGISTIC_HAZARD_GATE_FOLD_PLAN=$FOLD_PLAN"

"$PYTHON_BIN" -m compileall -q src tests
"$PYTEST_BIN" -q tests/test_stage03v_logistic_hazard.py tests/test_stage03v_logistic_hazard_causality.py
"$PYTHON_BIN" -m src.evaluation.stage03v_logistic_hazard \
  --db "$DB_PATH" \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --baseline-diagnostics reports/stage03v/baseline_diagnostics_report.json \
  --vol-scaled-sanity reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --fold-plan "$FOLD_PLAN" \
  --policy configs/stage03v_logistic_hazard_policy_v1.yaml \
  --output reports/stage03v/logistic_hazard_report.md \
  --summary-json reports/stage03v/logistic_hazard_report.json \
  --fold-metrics reports/stage03v/logistic_hazard_fold_metrics.csv \
  --slice-metrics reports/stage03v/logistic_hazard_slice_metrics.csv \
  --coefficients reports/stage03v/logistic_hazard_coefficients.csv \
  --model-manifest reports/stage03v/logistic_hazard_model_manifest.json \
  --feature-audit reports/stage03v/logistic_hazard_feature_audit.csv \
  --audit-sample reports/stage03v/logistic_hazard_audit_sample.csv \
  --asof-modes close_t_minus_1,close_t \
  --no-fetch
"$PYTHON_BIN" -m json.tool reports/stage03v/logistic_hazard_report.json >/dev/null
"$PYTHON_BIN" -m json.tool reports/stage03v/logistic_hazard_model_manifest.json >/dev/null
"$PYTHON_BIN" -m json.tool configs/stage03v_logistic_hazard_policy_v1.yaml >/dev/null

"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("reports/stage03v/logistic_hazard_report.json").read_text(encoding="utf-8"))
print(
    "STAGE03V_LOGISTIC_HAZARD_GATE="
    f"{report.get('status')} "
    f"db={report.get('source_db_path')} "
    f"fitted_models={report.get('fitted_model_count')} "
    f"validation_rows={report.get('validation_row_count_evaluated')} "
    f"primary_asof={report.get('primary_asof_mode')} "
    "report=reports/stage03v/logistic_hazard_report.md "
    "summary_json=reports/stage03v/logistic_hazard_report.json "
    "no_fetch=yes"
)
raise SystemExit(0 if report.get("status") == "pass" else 1)
PY
