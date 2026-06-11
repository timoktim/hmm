#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
PYTEST_BIN="${PYTEST_BIN:-.venv/bin/pytest}"
DB_PATH="${STAGE03V_V7_DB:-data/db/a_share_hmm_tushare_v7.duckdb}"

echo "STAGE03V_RISK_VALIDATION_GATE_DB=$DB_PATH"

"$PYTHON_BIN" -m compileall -q src tests
"$PYTEST_BIN" -q tests/test_stage03v_risk_validation.py tests/test_stage03v_risk_validation_boundaries.py
"$PYTHON_BIN" -m src.evaluation.stage03v_risk_validation \
  --db "$DB_PATH" \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --baseline-diagnostics reports/stage03v/baseline_diagnostics_report.json \
  --vol-scaled-sanity reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --logistic-hazard reports/stage03v/logistic_hazard_report.json \
  --calibration-readiness reports/stage03v/calibration_readiness_report.json \
  --calibration-fold-metrics reports/stage03v/calibration_fold_metrics.csv \
  --calibration-slice-metrics reports/stage03v/calibration_slice_metrics.csv \
  --calibration-bins reports/stage03v/calibration_curve_bins.csv \
  --clustered-inference reports/stage03v/clustered_inference_summary.csv \
  --readiness-matrix reports/stage03v/downside_readiness_matrix.csv \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --policy configs/stage03v_risk_validation_protocol_policy_v1.yaml \
  --protocol-output reports/stage03v/risk_validation_protocol.md \
  --output reports/stage03v/risk_validation_report.md \
  --summary-json reports/stage03v/risk_validation_report.json \
  --metrics reports/stage03v/risk_validation_metrics.csv \
  --downshift-report reports/stage03v/downshift_research_report.md \
  --downshift-json reports/stage03v/downshift_research_report.json \
  --candidate-matrix reports/stage03v/downshift_candidate_matrix.csv \
  --clustered-summary reports/stage03v/risk_validation_clustered_summary.csv \
  --audit-sample reports/stage03v/risk_validation_audit_sample.csv \
  --wp7-manifest reports/stage03v/wp7_final_gate_input_manifest.json \
  --no-fetch
"$PYTHON_BIN" -m json.tool reports/stage03v/risk_validation_report.json >/dev/null
"$PYTHON_BIN" -m json.tool reports/stage03v/downshift_research_report.json >/dev/null
"$PYTHON_BIN" -m json.tool reports/stage03v/wp7_final_gate_input_manifest.json >/dev/null
"$PYTHON_BIN" -m json.tool configs/stage03v_risk_validation_protocol_policy_v1.yaml >/dev/null

"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("reports/stage03v/risk_validation_report.json").read_text(encoding="utf-8"))
print(
    "STAGE03V_RISK_VALIDATION_GATE="
    f"{report.get('status')} "
    f"db={report.get('source_db_path')} "
    f"candidates={report.get('candidate_rows_evaluated')} "
    f"validation_pass_candidates={report.get('validation_pass_candidate_count')} "
    f"holdout_evaluated={report.get('prospective_holdout_rows_evaluated')} "
    "report=reports/stage03v/risk_validation_report.md "
    "summary_json=reports/stage03v/risk_validation_report.json "
    "no_fetch=yes"
)
raise SystemExit(0 if report.get("status") == "pass" else 1)
PY
