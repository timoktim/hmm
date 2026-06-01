from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATION_DIR = REPO_ROOT / "src" / "evaluation"
sys.path.insert(0, str(EVALUATION_DIR))

from baseline_collectors import collect_database_snapshot  # noqa: E402
from baseline_freeze import generate_baseline_snapshot  # noqa: E402


class BaselineFreezeTests(unittest.TestCase):
    def test_missing_db_generates_summary_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "reports" / "baseline"
            snapshot = generate_baseline_snapshot(
                db_path=root / "missing.duckdb",
                output_dir=output,
                working_dir=root,
                run_tests="no",
                register_evidence=True,
            )

            self.assertFalse(snapshot["database"]["db_available"])
            self.assertEqual(snapshot["summary_verdict"], "BaselineFreezePartialDueToDbUnavailable")
            self.assertTrue((output / "summary.md").exists())
            self.assertTrue((output / "baseline_snapshot.json").exists())
            self.assertTrue((output / "missing_artifacts.md").exists())
            self.assertTrue((output / "evidence_seed.jsonl").exists())

            loaded = json.loads((output / "baseline_snapshot.json").read_text(encoding="utf-8"))
            self.assertFalse(loaded["database"]["db_available"])
            self.assertFalse(loaded["external_fetch_attempted"])

    def test_no_fetch_is_default_and_never_calls_updaters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "out"
            snapshot = generate_baseline_snapshot(
                db_path=root / "missing.duckdb",
                output_dir=output,
                working_dir=root,
                run_tests="no",
            )

            self.assertTrue(snapshot["no_fetch_mode"])
            self.assertFalse(snapshot["external_fetch_attempted"])
            self.assertEqual(snapshot["validation_commands"][0]["reason"], "--run-tests no")

    @unittest.skipUnless(importlib.util.find_spec("duckdb"), "duckdb not installed")
    def test_missing_some_tables_does_not_crash(self) -> None:
        import duckdb  # type: ignore

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "partial.duckdb"
            con = duckdb.connect(str(db_path))
            con.execute("create table model_runs(run_id varchar, trade_date date, sector_id varchar)")
            con.execute("insert into model_runs values ('run_a', '2026-01-02', 's1')")
            con.close()

            snapshot = collect_database_snapshot(db_path)

            self.assertTrue(snapshot.db_available)
            model_runs = next(profile for profile in snapshot.table_profiles if profile.table_name == "model_runs")
            missing_table = next(
                profile for profile in snapshot.table_profiles if profile.table_name == "sector_state_daily"
            )
            self.assertEqual(model_runs.row_count, 1)
            self.assertFalse(missing_table.exists)

    @unittest.skipUnless(importlib.util.find_spec("duckdb"), "duckdb not installed")
    def test_existing_table_profiles_row_count_and_date_range(self) -> None:
        import duckdb  # type: ignore

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "profile.duckdb"
            con = duckdb.connect(str(db_path))
            con.execute(
                "create table sector_state_daily("
                "run_id varchar, trade_date date, sector_id varchar, "
                "feature_scope_id varchar, universe_id varchar)"
            )
            con.execute(
                "insert into sector_state_daily values "
                "('run_a', '2026-01-02', 's1', 'features_v0', 'universe_v0'),"
                "('run_a', '2026-01-03', 's2', 'features_v0', 'universe_v0')"
            )
            con.close()

            snapshot = collect_database_snapshot(db_path)
            profile = next(
                table for table in snapshot.table_profiles if table.table_name == "sector_state_daily"
            )

            self.assertEqual(profile.row_count, 2)
            self.assertEqual(profile.min_trade_date, "2026-01-02")
            self.assertEqual(profile.max_trade_date, "2026-01-03")
            self.assertEqual(profile.distinct_run_count, 1)
            self.assertEqual(profile.distinct_sector_count, 2)
            self.assertEqual(profile.feature_scope_id_sample, ["features_v0"])
            self.assertEqual(profile.universe_id_sample, ["universe_v0"])

    def test_json_loads_and_csv_is_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "out"
            generate_baseline_snapshot(
                db_path=root / "missing.duckdb",
                output_dir=output,
                working_dir=root,
                run_tests="no",
            )

            json.loads((output / "baseline_snapshot.json").read_text(encoding="utf-8"))
            with (output / "db_table_profile.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertGreaterEqual(len(rows), 1)
            self.assertIn("table_name", rows[0])


if __name__ == "__main__":
    unittest.main()
