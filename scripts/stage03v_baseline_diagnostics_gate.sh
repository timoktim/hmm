#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
PYTEST_BIN="${PYTEST_BIN:-.venv/bin/pytest}"
DB_PATH="${STAGE03V_V7_DB:-data/db/a_share_hmm_tushare_v7.duckdb}"

echo "STAGE03V_BASELINE_DIAGNOSTICS_GATE_DB=$DB_PATH"

"$PYTHON_BIN" -m compileall -q src tests
"$PYTEST_BIN" -q tests/test_stage03v_baseline_diagnostics.py tests/test_stage03v_baseline_causality.py
"$PYTHON_BIN" -m src.evaluation.stage03v_baseline_diagnostics \
  --db "$DB_PATH" \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --policy configs/stage03v_baseline_diagnostics_policy_v1.yaml \
  --output reports/stage03v/baseline_diagnostics_report.md \
  --summary-json reports/stage03v/baseline_diagnostics_report.json \
  --fold-metrics reports/stage03v/baseline_diagnostics_fold_metrics.csv \
  --slice-metrics reports/stage03v/baseline_diagnostics_slice_metrics.csv \
  --audit-sample reports/stage03v/baseline_diagnostics_audit_sample.csv \
  --no-fetch
"$PYTHON_BIN" -m json.tool reports/stage03v/baseline_diagnostics_report.json >/dev/null
"$PYTHON_BIN" -m json.tool configs/stage03v_baseline_diagnostics_policy_v1.yaml >/dev/null

"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("reports/stage03v/baseline_diagnostics_report.json").read_text(encoding="utf-8"))
print(
    "STAGE03V_BASELINE_DIAGNOSTICS_GATE="
    f"{report.get('status')} "
    f"db={report.get('source_db_path')} "
    f"baselines={report.get('baseline_count')} "
    f"validation_rows={report.get('validation_row_count_evaluated')} "
    f"report=reports/stage03v/baseline_diagnostics_report.md "
    f"summary_json=reports/stage03v/baseline_diagnostics_report.json "
    "no_fetch=yes"
)
raise SystemExit(0 if report.get("status") == "pass" else 1)
PY
