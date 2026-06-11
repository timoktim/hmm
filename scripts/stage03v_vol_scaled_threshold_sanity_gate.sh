#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
PYTEST_BIN="${PYTEST_BIN:-.venv/bin/pytest}"
DB_PATH="${STAGE03V_V7_DB:-data/db/a_share_hmm_tushare_v7.duckdb}"

echo "STAGE03V_VOL_SCALED_THRESHOLD_SANITY_GATE_DB=$DB_PATH"

"$PYTHON_BIN" -m compileall -q src tests
"$PYTEST_BIN" -q tests/test_stage03v_vol_scaled_threshold_sanity.py tests/test_stage03v_baseline_metric_sanity.py
"$PYTHON_BIN" -m src.evaluation.stage03v_vol_scaled_threshold_sanity \
  --db "$DB_PATH" \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --baseline-report reports/stage03v/baseline_diagnostics_report.json \
  --baseline-fold-metrics reports/stage03v/baseline_diagnostics_fold_metrics.csv \
  --baseline-slice-metrics reports/stage03v/baseline_diagnostics_slice_metrics.csv \
  --baseline-policy configs/stage03v_baseline_diagnostics_policy_v1.yaml \
  --policy configs/stage03v_vol_scaled_threshold_sanity_policy_v1.yaml \
  --output reports/stage03v/vol_scaled_threshold_sanity_report.md \
  --summary-json reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --vol-scaled-summary reports/stage03v/vol_scaled_threshold_slice_summary.csv \
  --metric-audit reports/stage03v/baseline_metric_sanity_audit.csv \
  --asof-shift-summary reports/stage03v/asof_shift_metric_sanity.csv \
  --no-fetch
"$PYTHON_BIN" -m json.tool reports/stage03v/vol_scaled_threshold_sanity_report.json >/dev/null
"$PYTHON_BIN" -m json.tool configs/stage03v_vol_scaled_threshold_sanity_policy_v1.yaml >/dev/null

"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("reports/stage03v/vol_scaled_threshold_sanity_report.json").read_text(encoding="utf-8"))
print(
    "STAGE03V_VOL_SCALED_THRESHOLD_SANITY_GATE="
    f"{report.get('status')} "
    f"db={report.get('source_db_path')} "
    f"candidates={report.get('vol_scaled_candidate_count')} "
    f"validation_rows={report.get('validation_row_count_evaluated')} "
    f"flagged_metrics={report.get('flagged_metric_row_count')} "
    f"baseline_sanity={report.get('baseline_sanity_status')} "
    f"wp4_recommendation={report.get('wp4_entry_recommendation')} "
    "report=reports/stage03v/vol_scaled_threshold_sanity_report.md "
    "summary_json=reports/stage03v/vol_scaled_threshold_sanity_report.json "
    "no_fetch=yes"
)
raise SystemExit(0 if report.get("status") == "pass" else 1)
PY
