from __future__ import annotations

import json
from pathlib import Path

from src.runtime import clean_snapshot_jobs as jobs
from src.runtime import db_workspace


def test_start_clean_snapshot_job_writes_progress_without_token(tmp_path: Path, monkeypatch) -> None:
    db_dir = tmp_path / "project" / "data" / "db"
    job_dir = tmp_path / "project" / "data" / "runtime" / "clean_snapshot_jobs"
    db_dir.mkdir(parents=True)
    monkeypatch.setattr(db_workspace, "DEFAULT_DB_DIR", db_dir)
    monkeypatch.setattr(db_workspace, "WORKSPACE_CONFIG_PATH", db_dir / "workspace_config.json")
    monkeypatch.setattr(db_workspace.settings, "db_path", db_dir / "a_share_hmm.duckdb")
    monkeypatch.setattr(jobs, "CLEAN_SNAPSHOT_JOB_DIR", job_dir)
    monkeypatch.setenv("ASHARE_HMM_TUSHARE_TOKEN", "<placeholder>")
    captured: dict[str, object] = {}

    class FakePopen:
        pid = 4321

        def __init__(self, command, cwd, stdout, stderr, start_new_session):  # noqa: ANN001
            captured["command"] = list(command)
            captured["cwd"] = cwd
            captured["start_new_session"] = start_new_session
            captured["stdout_is_stderr"] = stdout is stderr

    monkeypatch.setattr(jobs.subprocess, "Popen", FakePopen)

    job = jobs.start_clean_snapshot_job(
        target_db=db_dir / "target.duckdb",
        source_db=db_dir / "source.duckdb",
        start="20240102",
        end="20240104",
        max_trade_dates=2,
        max_stocks=10,
    )
    progress_json = jobs.progress_path(str(job["job_id"]))
    payload = json.loads(progress_json.read_text(encoding="utf-8"))
    text = progress_json.read_text(encoding="utf-8")
    command = captured["command"]

    assert payload["status"] == "running"
    assert payload["pid"] == 4321
    assert payload["stock_level_label"] == "个股日线批量拉取（按交易日/API，不逐股循环）"
    assert "--progress-json" in command
    assert "--job-id" in command
    assert "--mode" in command
    assert "<placeholder>" not in text
    assert "ASHARE_HMM_TUSHARE_TOKEN" not in text
    assert captured["start_new_session"] is True


def test_list_clean_snapshot_jobs_restores_persisted_progress(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(jobs, "CLEAN_SNAPSHOT_JOB_DIR", tmp_path)
    monkeypatch.setattr(jobs, "_pid_running", lambda pid: True)
    first_dir = tmp_path / "clean-a"
    second_dir = tmp_path / "clean-b"
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)
    (first_dir / "progress.json").write_text(
        json.dumps({"job_id": "clean-a", "status": "running", "pid": 1, "updated_at": "2026-01-01T00:00:00"}),
        encoding="utf-8",
    )
    (second_dir / "progress.json").write_text(
        json.dumps({"job_id": "clean-b", "status": "pass", "updated_at": "2026-01-02T00:00:00"}),
        encoding="utf-8",
    )

    listed = jobs.list_clean_snapshot_jobs()

    assert [item["job_id"] for item in listed] == ["clean-b", "clean-a"]
