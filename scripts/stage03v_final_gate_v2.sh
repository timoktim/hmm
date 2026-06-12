#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
PYTEST_BIN="${PYTEST_BIN:-.venv/bin/pytest}"
DB_PATH="${STAGE03V_V7_DB:-data/db/a_share_hmm_tushare_v7.duckdb}"

echo "STAGE03V_FINAL_GATE_V2_DB=$DB_PATH"

"$PYTHON_BIN" -m compileall -q src tests
"$PYTEST_BIN" -q tests/test_stage03v_final_gate_v2.py tests/test_stage03v_final_gate_v2_boundaries.py

"$PYTHON_BIN" -m src.evaluation.stage03v_final_gate_v2 \
  --db "$DB_PATH" \
  --scope-freeze reports/stage03v/stage03v_wp0_scope_freeze_report.json \
  --sample-feasibility reports/stage03v/sample_feasibility_report.json \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --baseline-diagnostics reports/stage03v/baseline_diagnostics_report.json \
  --vol-scaled-sanity reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --fold-plan-v2 reports/stage03v/purge_embargo_fold_plan_v2.json \
  --fold-magnitude-overview reports/stage03v/fold_plan_magnitude_overview.csv \
  --trial-accounting reports/stage03v/validation_trial_accounting.json \
  --logistic-hazard reports/stage03v/logistic_hazard_report.json \
  --calibration-readiness reports/stage03v/calibration_readiness_report.json \
  --downshift-experiment reports/stage03v/downshift_experiment_report.json \
  --downshift-arm-metrics reports/stage03v/downshift_experiment_arm_metrics.csv \
  --ledger-template reports/stage04/prospective_validation_ledger.stage03v.template.jsonl \
  --policy configs/stage03v_final_gate_policy_v2.yaml \
  --output reports/stage03v/stage03v1_final_gate_v2_report.md \
  --summary-json reports/stage03v/stage03v1_final_gate_v2_report.json \
  --verdict-json reports/stage03v/stage03v1_final_gate_v2_verdict.json \
  --evidence-matrix reports/stage03v/stage03v1_final_gate_v2_evidence_matrix.csv \
  --artifact-manifest reports/stage03v/stage03v1_final_gate_v2_artifact_manifest.json \
  --rerun1-input-manifest reports/stage03v/stage03v1_final_gate_v2_rerun1_input_manifest.json \
  --holdout-status reports/stage03v/stage03v1_prospective_holdout_status_v2.json \
  --post-gate-action-plan reports/stage03v/stage03v1_post_gate_action_plan_v2.md \
  --audit-sample reports/stage03v/stage03v1_final_gate_v2_audit_sample.csv \
  --no-fetch

"$PYTHON_BIN" -m json.tool reports/stage03v/stage03v1_final_gate_v2_report.json >/dev/null
"$PYTHON_BIN" -m json.tool reports/stage03v/stage03v1_final_gate_v2_verdict.json >/dev/null
"$PYTHON_BIN" -m json.tool reports/stage03v/stage03v1_final_gate_v2_artifact_manifest.json >/dev/null
"$PYTHON_BIN" -m json.tool reports/stage03v/stage03v1_final_gate_v2_rerun1_input_manifest.json >/dev/null
"$PYTHON_BIN" -m json.tool reports/stage03v/stage03v1_prospective_holdout_status_v2.json >/dev/null
"$PYTHON_BIN" -m json.tool configs/stage03v_final_gate_policy_v2.yaml >/dev/null

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/stage03v_final_gate_v2_missing_v7.XXXXXX")"
"$PYTHON_BIN" -m src.evaluation.stage03v_final_gate_v2 \
  --db "$TMP_DIR/missing_v7.duckdb" \
  --policy configs/stage03v_final_gate_policy_v2.yaml \
  --output "$TMP_DIR/stage03v1_final_gate_v2_report.md" \
  --summary-json "$TMP_DIR/stage03v1_final_gate_v2_report.json" \
  --verdict-json "$TMP_DIR/stage03v1_final_gate_v2_verdict.json" \
  --evidence-matrix "$TMP_DIR/stage03v1_final_gate_v2_evidence_matrix.csv" \
  --artifact-manifest "$TMP_DIR/stage03v1_final_gate_v2_artifact_manifest.json" \
  --rerun1-input-manifest "$TMP_DIR/stage03v1_final_gate_v2_rerun1_input_manifest.json" \
  --holdout-status "$TMP_DIR/stage03v1_prospective_holdout_status_v2.json" \
  --post-gate-action-plan "$TMP_DIR/stage03v1_post_gate_action_plan_v2.md" \
  --audit-sample "$TMP_DIR/stage03v1_final_gate_v2_audit_sample.csv" \
  --no-fetch >/dev/null
"$PYTHON_BIN" -m json.tool "$TMP_DIR/stage03v1_final_gate_v2_report.json" >/dev/null

"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("reports/stage03v/stage03v1_final_gate_v2_report.json").read_text(encoding="utf-8"))
print(
    "STAGE03V_FINAL_GATE_V2="
    f"{report.get('status')} "
    f"verdict={report.get('final_gate_verdict')} "
    f"primary_risk={report.get('primary_risk_metric_comparison_status')} "
    f"model_discrimination={report.get('model_discrimination_status')} "
    f"holdout_min_20d_days={report.get('prospective_holdout_min_complete_20d_label_trade_dates')} "
    f"holdout_min_blocks={report.get('prospective_holdout_min_market_event_blocks')} "
    f"db={report.get('source_db_path')} "
    "report=reports/stage03v/stage03v1_final_gate_v2_report.md "
    "summary_json=reports/stage03v/stage03v1_final_gate_v2_report.json "
    "no_fetch=yes"
)
raise SystemExit(0 if report.get("status") == "pass" else 1)
PY
