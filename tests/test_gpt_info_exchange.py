from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from src.integrations import gpt_info_exchange


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = Path("configs/gpt_info_exchange_policy_v1.yaml")
FORBIDDEN_OUTPUT_TERMS = [
    "/Users/",
    "/private/tmp",
    "data/db/",
    ".duckdb",
    "buy_signal",
    "sell_signal",
    "position_size",
    "position_sizing",
    "trade_instruction",
    "portfolio_action",
    "execution_order",
]
FORBIDDEN_FIELD_TOKENS = [
    "buy_signal",
    "sell_signal",
    "position_size",
    "position_sizing",
    "recommendation",
    "execution",
    "portfolio_action",
]


def _run_export(tmp_path: Path, *extra: str, no_push: bool = True) -> tuple[subprocess.CompletedProcess[str], Path]:
    output_dir = tmp_path / "latest"
    archive_dir = tmp_path / "archive"
    command = [
        sys.executable,
        "-m",
        "src.integrations.gpt_info_exchange",
        "--policy",
        str(POLICY_PATH),
        "--output-dir",
        str(output_dir),
        "--archive-dir",
        str(archive_dir),
        "--synthetic",
    ]
    if no_push:
        command.append("--no-push")
    command.extend(extra)
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, output_dir


def _read_all_text(root: Path) -> str:
    parts: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def test_policy_config_loads_and_validates() -> None:
    policy = gpt_info_exchange.load_policy(POLICY_PATH)

    assert gpt_info_exchange.validate_policy(policy) == []
    assert policy["index_id"] == "GPT-EXCHANGE-WP0-v1"
    assert policy["include_raw_ohlcv"] is False
    assert policy["include_full_matrices"] is False


def test_exporter_builds_required_output_file_set(tmp_path: Path) -> None:
    result, output_dir = _run_export(tmp_path)

    assert result.returncode == 0, result.stderr
    expected = set(gpt_info_exchange.load_policy(POLICY_PATH)["allowed_output_files"])
    produced = {path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*") if path.is_file()}
    assert expected == produced


def test_signal_snapshot_lite_contains_only_allowed_columns_and_respects_cap(tmp_path: Path) -> None:
    result, output_dir = _run_export(tmp_path, "--max-rows", "3")

    assert result.returncode == 0, result.stderr
    snapshot = pd.read_csv(output_dir / "signal_snapshot_lite.csv")
    assert list(snapshot.columns) == gpt_info_exchange.ALLOWED_LITE_COLUMNS
    assert len(snapshot) == 3
    assert snapshot["not_trading_output"].eq("yes").all()


def test_watchlists_respect_max_row_cap(tmp_path: Path) -> None:
    result, output_dir = _run_export(tmp_path, "--max-watchlist-rows", "2")

    assert result.returncode == 0, result.stderr
    for rel in gpt_info_exchange.WATCHLIST_FILES.values():
        watchlist = pd.read_csv(output_dir / rel)
        assert len(watchlist) <= 2
        assert "watch_reason" in watchlist.columns


def test_missing_exchange_repo_does_not_fail_local_export(tmp_path: Path) -> None:
    result, output_dir = _run_export(tmp_path)

    assert result.returncode == 0, result.stderr
    manifest = json.loads((output_dir / "exchange_manifest.json").read_text(encoding="utf-8"))
    assert manifest["exchange_repo_status"] == "unavailable_or_not_configured"
    assert manifest["sync_status"] == "skipped_exchange_repo_unavailable"
    assert manifest["push_executed"] == "no"


def test_push_without_commit_is_rejected(tmp_path: Path) -> None:
    result, _output_dir = _run_export(tmp_path, "--push", no_push=False)

    assert result.returncode != 0
    assert "--push requires --commit" in result.stdout


def test_commit_without_write_exchange_is_rejected(tmp_path: Path) -> None:
    result, _output_dir = _run_export(tmp_path, "--commit")

    assert result.returncode != 0
    assert "--commit requires --write-exchange" in result.stdout


def test_exchange_git_commit_leaves_temp_repo_clean(tmp_path: Path) -> None:
    exchange_dir = tmp_path / "hmm-info-exchange"
    subprocess.run(["git", "init", str(exchange_dir)], check=True, text=True, capture_output=True)
    subprocess.run(["git", "-C", str(exchange_dir), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(exchange_dir), "config", "user.name", "GPT Exchange Test"], check=True)

    result, _output_dir = _run_export(
        tmp_path / "source",
        "--exchange-dir",
        str(exchange_dir),
        "--bootstrap-exchange-repo",
        "--write-exchange",
        "--commit",
        "--no-push",
    )

    assert result.returncode == 0, result.stderr
    status = subprocess.run(
        ["git", "-C", str(exchange_dir), "status", "--porcelain"],
        check=True,
        text=True,
        capture_output=True,
    )
    assert status.stdout == ""
    manifest_path = exchange_dir / "latest/exchange_manifest.json"
    assert manifest_path.exists()
    manifest_text = manifest_path.read_text(encoding="utf-8")
    for term in FORBIDDEN_OUTPUT_TERMS:
        assert term not in manifest_text


def test_bundle_contains_required_not_trading_warning(tmp_path: Path) -> None:
    result, output_dir = _run_export(tmp_path)

    assert result.returncode == 0, result.stderr
    text = (output_dir / "signal_bundle.md").read_text(encoding="utf-8")
    assert gpt_info_exchange.WARNING_TEXT in text
    payload = json.loads((output_dir / "signal_bundle.json").read_text(encoding="utf-8"))
    assert payload["not_trading_output_warning"] == gpt_info_exchange.WARNING_TEXT


def test_bundle_contains_no_forbidden_terms_or_private_paths(tmp_path: Path) -> None:
    result, output_dir = _run_export(tmp_path)

    assert result.returncode == 0, result.stderr
    all_text = _read_all_text(output_dir)
    for term in FORBIDDEN_OUTPUT_TERMS:
        assert term not in all_text


def test_no_buy_sell_or_position_decision_fields_are_created(tmp_path: Path) -> None:
    result, output_dir = _run_export(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads((output_dir / "signal_bundle.json").read_text(encoding="utf-8"))
    keys_text = json.dumps(list(_walk_keys(payload)), ensure_ascii=False)
    for term in FORBIDDEN_FIELD_TOKENS:
        assert term not in keys_text


def _walk_keys(value: object) -> list[str]:
    if isinstance(value, dict):
        keys = list(value)
        for child in value.values():
            keys.extend(_walk_keys(child))
        return keys
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_walk_keys(item))
        return out
    return []


def test_invalidated_artifact_warning_is_present(tmp_path: Path) -> None:
    result, output_dir = _run_export(tmp_path)

    assert result.returncode == 0, result.stderr
    assert gpt_info_exchange.INVALIDATED_ARTIFACT_WARNING in (output_dir / "signal_bundle.md").read_text(encoding="utf-8")
    provenance = json.loads((output_dir / "provenance.json").read_text(encoding="utf-8"))
    assert "old WP4-WP6" in provenance["invalidated_artifact_policy"]


def test_prompt_template_requires_external_search_and_no_trading_output(tmp_path: Path) -> None:
    result, output_dir = _run_export(tmp_path)

    assert result.returncode == 0, result.stderr
    prompt = (output_dir / "prompt_template.md").read_text(encoding="utf-8")
    assert "web/search" in prompt
    assert "Do not output trading" in prompt
