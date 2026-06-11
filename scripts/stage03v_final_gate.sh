#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
PYTEST_BIN="${PYTEST_BIN:-.venv/bin/pytest}"
DB_PATH="${STAGE03V_V7_DB:-data/db/a_share_hmm_tushare_v7.duckdb}"

echo "STAGE03V_FINAL_GATE_DB=$DB_PATH"

"$PYTHON_BIN" -m compileall -q src tests
"$PYTEST_BIN" -q tests/test_stage03v_final_gate.py tests/test_stage03v_final_gate_boundaries.py
"$PYTHON_BIN" -m src.evaluation.stage03v_final_gate \
  --db "$DB_PATH" \
  --scope-freeze reports/stage03v/stage03v_wp0_scope_freeze_report.json \
  --sample-feasibility reports/stage03v/sample_feasibility_report.json \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --baseline-diagnostics reports/stage03v/baseline_diagnostics_report.json \
  --vol-scaled-sanity reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --logistic-hazard reports/stage03v/logistic_hazard_report.json \
  --calibration-readiness reports/stage03v/calibration_readiness_report.json \
  --risk-validation reports/stage03v/risk_validation_report.json \
  --downshift-research reports/stage03v/downshift_research_report.json \
  --wp7-input-manifest reports/stage03v/wp7_final_gate_input_manifest.json \
  --ledger-template reports/stage04/prospective_validation_ledger.stage03v.template.jsonl \
  --policy configs/stage03v_final_gate_policy_v1.yaml \
  --output reports/stage03v/stage03v1_final_gate_report.md \
  --summary-json reports/stage03v/stage03v1_final_gate_report.json \
  --verdict-json reports/stage03v/stage03v1_final_gate_verdict.json \
  --evidence-matrix reports/stage03v/stage03v1_final_gate_evidence_matrix.csv \
  --artifact-manifest reports/stage03v/stage03v1_final_gate_artifact_manifest.json \
  --holdout-status reports/stage03v/stage03v1_prospective_holdout_status.json \
  --post-gate-action-plan reports/stage03v/stage03v1_post_gate_action_plan.md \
  --audit-sample reports/stage03v/stage03v1_final_gate_audit_sample.csv \
  --no-fetch
"$PYTHON_BIN" -m json.tool reports/stage03v/stage03v1_final_gate_report.json >/dev/null
"$PYTHON_BIN" -m json.tool reports/stage03v/stage03v1_final_gate_verdict.json >/dev/null
"$PYTHON_BIN" -m json.tool reports/stage03v/stage03v1_final_gate_artifact_manifest.json >/dev/null
"$PYTHON_BIN" -m json.tool reports/stage03v/stage03v1_prospective_holdout_status.json >/dev/null
"$PYTHON_BIN" -m json.tool configs/stage03v_final_gate_policy_v1.yaml >/dev/null

"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("reports/stage03v/stage03v1_final_gate_report.json").read_text(encoding="utf-8"))
print(
    "STAGE03V_FINAL_GATE="
    f"{report.get('status')} "
    f"verdict={report.get('final_gate_verdict')} "
    f"db={report.get('source_db_path')} "
    f"holdout_evaluated={report.get('prospective_holdout_rows_evaluated')} "
    f"decision_support_gate={report.get('decision_support_promotion_gate_status')} "
    "report=reports/stage03v/stage03v1_final_gate_report.md "
    "summary_json=reports/stage03v/stage03v1_final_gate_report.json "
    "no_fetch=yes"
)
raise SystemExit(0 if report.get("status") == "pass" else 1)
PY
