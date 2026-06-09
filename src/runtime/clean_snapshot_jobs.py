from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT, project_relative_path, settings
from src.runtime import db_workspace


CLEAN_SNAPSHOT_JOB_DIR = PROJECT_ROOT / "data" / "runtime" / "clean_snapshot_jobs"
TERMINAL_STATUSES = {"pass", "failed", "plan_only", "unknown_stopped"}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_json_default(value: object) -> str:
    return str(value)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_safe_json_default) + "\n", encoding="utf-8")
    tmp.replace(path)


def make_job_id() -> str:
    return f"clean-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"


def job_dir(job_id: str) -> Path:
    return CLEAN_SNAPSHOT_JOB_DIR / str(job_id)


def progress_path(job_id: str) -> Path:
    return job_dir(job_id) / "progress.json"


def log_path(job_id: str) -> Path:
    return job_dir(job_id) / "run.log"


def summary_path(job_id: str) -> Path:
    return job_dir(job_id) / "summary.json"


def report_path(job_id: str) -> Path:
    return job_dir(job_id) / "report.md"


def read_job_progress(job_id: str) -> dict[str, Any]:
    return refresh_job_status(_read_json(progress_path(job_id)))


def _pid_running(pid: object) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def refresh_job_status(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    status = str(payload.get("status") or "").lower()
    if status in TERMINAL_STATUSES:
        return payload
    if payload.get("pid") and not _pid_running(payload.get("pid")):
        payload = dict(payload)
        payload["status"] = "unknown_stopped"
        payload["updated_at"] = _now_iso()
        job_id = str(payload.get("job_id") or "")
        if job_id:
            _write_json(progress_path(job_id), payload)
    return payload


def list_clean_snapshot_jobs(limit: int = 20) -> list[dict[str, Any]]:
    if not CLEAN_SNAPSHOT_JOB_DIR.exists():
        return []
    jobs: list[dict[str, Any]] = []
    for path in CLEAN_SNAPSHOT_JOB_DIR.glob("*/progress.json"):
        payload = refresh_job_status(_read_json(path))
        if payload:
            jobs.append(payload)
    jobs.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return jobs[: max(0, int(limit))]


def has_tushare_token() -> bool:
    return bool((os.getenv("ASHARE_HMM_TUSHARE_TOKEN") or settings.tushare_token or "").strip())


def _display_command(command: list[str]) -> str:
    display = ["python" if index == 0 else part for index, part in enumerate(command)]
    sanitized: list[str] = []
    for part in display:
        path = Path(part)
        if path.is_absolute():
            sanitized.append(project_relative_path(path))
        else:
            sanitized.append(part)
    return " ".join(sanitized)


def start_clean_snapshot_job(
    *,
    target_db: str | Path,
    source_db: str | Path,
    start: str,
    end: str,
    copy_user_assets: bool = True,
    max_trade_dates: int | None = None,
    max_stocks: int | None = None,
    allow_existing: bool = False,
    force_refresh: bool = False,
) -> dict[str, Any]:
    safe_target = db_workspace.project_safe_db_path(target_db)
    safe_source = db_workspace.project_safe_db_path(source_db)
    job_id = make_job_id()
    progress_file = progress_path(job_id)
    summary_file = summary_path(job_id)
    report_file = report_path(job_id)
    log_file = log_path(job_id)
    command = [
        sys.executable,
        "-m",
        "src.data_pipeline.clean_tushare_snapshot",
        "--target-db",
        str(safe_target),
        "--source-db",
        str(safe_source),
        "--start",
        str(start),
        "--end",
        str(end),
        "--mode",
        "build",
        "--summary-json",
        str(summary_file),
        "--report",
        str(report_file),
        "--progress-json",
        str(progress_file),
        "--job-id",
        job_id,
    ]
    if not copy_user_assets:
        command.append("--skip-user-assets")
    if max_trade_dates is not None and int(max_trade_dates) > 0:
        command.extend(["--max-trade-dates", str(int(max_trade_dates))])
    if max_stocks is not None and int(max_stocks) > 0:
        command.extend(["--max-stocks", str(int(max_stocks))])
    if allow_existing:
        command.append("--allow-existing")
    if force_refresh:
        command.append("--force-refresh")

    initial = {
        "snapshot_profile": "clean_tushare_snapshot",
        "job_id": job_id,
        "status": "queued",
        "stage": "preflight",
        "stage_index": 1,
        "stage_total": 14,
        "stage_progress": 0.0,
        "overall_progress": 0.0,
        "stock_progress": 0.0,
        "stock_current": 0,
        "stock_total": 0,
        "stock_level_label": "个股日线批量拉取（按交易日/API，不逐股循环）",
        "message": "queued",
        "target_db": project_relative_path(safe_target),
        "source_db": project_relative_path(safe_source),
        "summary_json": project_relative_path(summary_file),
        "report": project_relative_path(report_file),
        "log": project_relative_path(log_file),
        "command": _display_command(command),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _write_json(progress_file, initial)

    with log_file.open("ab") as log:
        process = subprocess.Popen(command, cwd=str(PROJECT_ROOT), stdout=log, stderr=log, start_new_session=True)
    running = dict(initial)
    running.update({"status": "running", "pid": int(process.pid), "message": "background build started", "updated_at": _now_iso()})
    _write_json(progress_file, running)
    return running
