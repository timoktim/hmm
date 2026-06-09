from __future__ import annotations

import inspect
import json
from pathlib import Path

import duckdb
import pytest

from src.data_pipeline.storage import DuckDBStorage
from src.runtime import db_workspace
from src.ui import database_workspace_page


@pytest.fixture()
def workspace_paths(tmp_path, monkeypatch):
    db_dir = tmp_path / "project" / "data" / "db"
    db_dir.mkdir(parents=True)
    monkeypatch.setattr(db_workspace, "DEFAULT_DB_DIR", db_dir)
    monkeypatch.setattr(db_workspace, "WORKSPACE_CONFIG_PATH", db_dir / "workspace_config.json")
    monkeypatch.setattr(db_workspace.settings, "db_path", db_dir / "a_share_hmm.duckdb")
    return db_dir


def _table_names(path: Path) -> set[str]:
    with duckdb.connect(str(path), read_only=True) as con:
        rows = con.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            """
        ).fetchall()
    return {str(row[0]) for row in rows}


def test_resolve_active_db_path_defaults_to_settings(workspace_paths):
    active = db_workspace.resolve_active_db_path(session_state={})

    assert active == workspace_paths / "a_share_hmm.duckdb"


def test_create_database_initializes_schema(workspace_paths):
    target = workspace_paths / "a_share_hmm_tushare_v1.duckdb"

    info = db_workspace.create_database(target, label="Tushare v1")
    DuckDBStorage(target).init_schema()

    tables = _table_names(target)
    assert info.exists is True
    assert target.exists()
    assert "stock_ohlcv" in tables
    assert "qfq_rebuild_runs" in tables
    assert "database_workspace_metadata" in tables


def test_create_database_refuses_overwrite(workspace_paths):
    target = workspace_paths / "exists.duckdb"
    db_workspace.create_database(target)

    with pytest.raises(FileExistsError):
        db_workspace.create_database(target)


def test_list_database_files_can_exclude_running_snapshot_targets(workspace_paths):
    included = workspace_paths / "included.duckdb"
    excluded = workspace_paths / "running_target.duckdb"
    db_workspace.create_database(included)
    db_workspace.create_database(excluded)

    infos = db_workspace.list_database_files(exclude_paths=[excluded])
    display_paths = {info.display_path for info in infos}

    assert "data/db/included.duckdb" in display_paths
    assert "data/db/running_target.duckdb" not in display_paths


def test_open_existing_database_requires_existing_file(workspace_paths):
    missing = workspace_paths / "missing.duckdb"

    with pytest.raises(FileNotFoundError):
        db_workspace.set_active_db_path(missing, session_state={})

    assert not missing.exists()


def test_open_existing_database_rejects_non_duckdb_suffix(workspace_paths):
    text_file = workspace_paths / "not_a_db.txt"
    text_file.write_text("not duckdb", encoding="utf-8")

    with pytest.raises(ValueError):
        db_workspace.set_active_db_path(text_file, session_state={})


def test_set_active_db_path_persists_workspace_config(workspace_paths):
    target = workspace_paths / "active.duckdb"
    db_workspace.create_database(target)
    state: dict[str, object] = {}

    db_workspace.set_active_db_path(target, session_state=state)
    payload = json.loads((workspace_paths / "workspace_config.json").read_text(encoding="utf-8"))

    assert payload["active_db_path"] == "data/db/active.duckdb"
    assert state[db_workspace.SESSION_ACTIVE_DB_KEY] == "data/db/active.duckdb"
    assert db_workspace.resolve_active_db_path(session_state={}) == target


def test_archive_database_copies_without_moving(workspace_paths):
    source = workspace_paths / "source.duckdb"
    db_workspace.create_database(source)
    source_size = source.stat().st_size

    archive_info = db_workspace.archive_database(source)

    assert source.exists()
    assert archive_info.path.exists()
    assert archive_info.path != source
    assert archive_info.size_bytes >= source_size
    assert archive_info.display_path.startswith("data/db/archive/")


def test_validate_database_reports_missing_tables(workspace_paths):
    empty = workspace_paths / "empty.duckdb"
    with duckdb.connect(str(empty)):
        pass

    validation = db_workspace.validate_database(empty)

    assert validation.exists is True
    assert validation.can_connect is True
    assert validation.schema_initialized is False
    assert "stock_ohlcv" in validation.missing_tables


def test_database_summary_uses_project_relative_paths(workspace_paths):
    target = workspace_paths / "summary.duckdb"
    db_workspace.create_database(target)

    summary = db_workspace.database_summary(target)

    assert summary.path_display == "data/db/summary.duckdb"
    assert "/Users/" not in summary.path_display
    assert ".codex_worktrees" not in summary.path_display


def test_workspace_metadata_probes_share_runtime_connection_config(workspace_paths):
    target = workspace_paths / "same_config.duckdb"
    db_workspace.create_database(target)

    with DuckDBStorage(target).connect():
        validation = db_workspace.validate_database(target)
        summary = db_workspace.database_summary(target)

    assert validation.can_connect is True
    assert summary.validation.can_connect is True
    assert summary.path_display == "data/db/same_config.duckdb"


def test_app_uses_resolved_active_db_path():
    app_source = Path("app.py").read_text(encoding="utf-8")

    assert "resolve_active_db_path()" in app_source
    assert "DuckDBStorage(path)" in app_source
    assert "storage = DuckDBStorage()" not in app_source


def test_no_destructive_reset_api():
    public_names = [name.lower() for name in dir(db_workspace) if not name.startswith("_")]
    forbidden_public_fragments = ["reset_database", "delete_database", "drop_database", "clear_database"]
    assert not any(fragment in name for name in public_names for fragment in forbidden_public_fragments)

    ui_source = inspect.getsource(database_workspace_page)
    forbidden_visible_text = ["重置数据库", "Reset DB", "Clear DB", "Drop DB"]
    assert not any(text in ui_source for text in forbidden_visible_text)


def test_database_workspace_page_can_import_and_render_current_info(workspace_paths):
    target = workspace_paths / "render.duckdb"
    db_workspace.create_database(target)

    database_workspace_page.render_database_workspace(active_db_path=target)

    source = inspect.getsource(database_workspace_page.render_database_workspace)
    assert "当前数据库" in source


def test_database_workspace_page_has_friendly_empty_state():
    source = inspect.getsource(database_workspace_page._render_open_existing)

    assert "暂未发现 .duckdb 文件" in source
    assert "重置数据库" not in source


def test_clean_snapshot_page_has_background_two_level_progress():
    ui_source = inspect.getsource(database_workspace_page)

    assert "后台 Clean Snapshot Build" in ui_source
    assert "总进度" in ui_source
    assert "个股日线批量拉取" in ui_source
    assert "start_clean_snapshot_job" in ui_source
    assert "_running_snapshot_target_paths" in ui_source
    assert "exclude_paths=running_snapshot_targets" in ui_source
    assert "200/min" in ui_source
