from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_no_private_paths.sh"


def run_checker(*paths: Path) -> subprocess.CompletedProcess[str]:
    command = ["bash", str(CHECK_SCRIPT), *(str(path) for path in paths)]
    return subprocess.run(command, cwd=REPO_ROOT, check=False, text=True, capture_output=True)


def test_committed_docs_and_reports_do_not_expose_private_paths() -> None:
    result = run_checker()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PRIVATE_PATH_HYGIENE=pass" in result.stdout


def test_private_path_checker_rejects_machine_specific_paths(tmp_path: Path) -> None:
    bad = tmp_path / "bad_report.md"
    bad.write_text(
        "db path: /Users/example/HMM高阶分析器/data/db/a_share_hmm.duckdb\n",
        encoding="utf-8",
    )

    result = run_checker(bad)

    assert result.returncode == 1
    assert "PRIVATE_PATH_HYGIENE=fail" in result.stdout
    assert "mac_user_path" in result.stdout or "local_project_name" in result.stdout


def test_private_path_checker_allows_generic_db_placeholder(tmp_path: Path) -> None:
    policy_example = tmp_path / "policy_example.md"
    policy_example.write_text(
        "Use ASHARE_HMM_DB_PATH=/absolute/path/to/a_share_hmm.duckdb for local handoff examples.\n",
        encoding="utf-8",
    )

    result = run_checker(policy_example)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PRIVATE_PATH_HYGIENE=pass" in result.stdout
