#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
PYTEST_BIN="${PYTEST_BIN:-.venv/bin/pytest}"
DB_PATH="${STAGE03V_V7_DB:-data/db/a_share_hmm_tushare_v7.duckdb}"

echo "STAGE03V_RERUN1_B0_GATE_DB=$DB_PATH"

"$PYTHON_BIN" -m compileall -q src tests
"$PYTEST_BIN" -q tests/test_stage03v_fold_plan_magnitude_gates.py
"$PYTHON_BIN" -m src.evaluation.stage03v_fold_plan_magnitude \
  --db "$DB_PATH" \
  --target-support reports/stage03v/risk_event_target_support.json \
  --output-plan reports/stage03v/purge_embargo_fold_plan_v2.json \
  --overview-md reports/stage03v/fold_plan_magnitude_overview.md \
  --overview-csv reports/stage03v/fold_plan_magnitude_overview.csv \
  --trial-accounting reports/stage03v/validation_trial_accounting.json \
  --fold-count 10 \
  --no-fetch
"$PYTHON_BIN" -m json.tool reports/stage03v/purge_embargo_fold_plan_v2.json >/dev/null
"$PYTHON_BIN" -m json.tool reports/stage03v/validation_trial_accounting.json >/dev/null

"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("reports/stage03v/purge_embargo_fold_plan_v2.json").read_text(encoding="utf-8"))
overview = report.get("magnitude_overview", {})
print(
    "STAGE03V_RERUN1_B0_GATE="
    f"{report.get('status')} "
    f"db={report.get('source_db_path')} "
    f"folds={report.get('fold_count')} "
    f"validation_trade_dates={overview.get('total_validation_trade_dates')} "
    f"min_fold_validation_dates={overview.get('min_fold_validation_trade_dates')} "
    f"min_slice_train_rows={overview.get('min_fold_slice_train_rows')} "
    f"holdout_labels={report.get('prospective_holdout_label_consumed_count')} "
    "plan=reports/stage03v/purge_embargo_fold_plan_v2.json "
    "overview=reports/stage03v/fold_plan_magnitude_overview.md "
    "no_fetch=yes"
)
raise SystemExit(0 if report.get("status") == "pass" else 1)
PY
