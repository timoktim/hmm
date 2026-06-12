from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.signals.signal_panel_snapshot import (
    ACCEPTED_SIGNAL_SOURCE_PATHS,
    INVALIDATED_SIGNAL_SOURCE_FORBIDDEN,
    STAGE03V_CLOSEOUT_REPORT_PATH,
    STAGE03V_FINAL_GATE_V2_PATH,
    STAGE03V_HANDOFF_PATH,
    STAGE03V_INVALIDATED_REGISTRY_PATH,
    build_signal_panel_snapshot,
    build_signal_panel_snapshot_from_frames,
    validate_snapshot_schema,
)


INDEX_ID = "GPT-EXCHANGE-WP0-v1"
SOURCE_REPO = "timoktim/hmm"
DEFAULT_POLICY_PATH = Path("configs/gpt_info_exchange_policy_v1.yaml")
DEFAULT_OUTPUT_DIR = Path("reports/gpt_exchange/latest")
DEFAULT_ARCHIVE_DIR = Path("reports/gpt_exchange/archive")
WARNING_TEXT = (
    "This bundle is a research/reference artifact for human review. It is not a trading, sizing, "
    "buy/sell, recommendation, execution, or portfolio-action instruction."
)
INVALIDATED_ARTIFACT_WARNING = (
    "Invalidated pre-RERUN1 WP4-WP6 and old WP7-v1 artifacts are not used as signal evidence."
)
UNAVAILABLE = "unavailable"

ALLOWED_LITE_COLUMNS = [
    "signal_date",
    "sector_id",
    "sector_name",
    "sector_type",
    "data_freshness_status",
    "volatility_band",
    "volatility_percentile_cs",
    "downside_vol_share_20d",
    "downside_vol_share_60d",
    "negative_return_day_share_20d",
    "hmm_state_label",
    "hmm_confidence",
    "prob_trend_up",
    "prob_neutral",
    "prob_risk_off",
    "hsmm_state_phase",
    "hsmm_state_age_days",
    "hsmm_age_bucket",
    "hsmm_duration_percentile",
    "exit_tendency_5d",
    "exit_tendency_10d",
    "exit_tendency_20d",
    "stage03v_readiness_summary",
    "stage03v_probability_display_status",
    "stage03v_probability_source_status",
    "stage03v_risk_ordinal",
    "model_baseline_alignment_status",
    "human_review_note",
    "not_trading_output",
]

WATCHLIST_FILES = {
    "high_baseline_risk": "watchlists/high_baseline_risk.csv",
    "model_baseline_conflicts": "watchlists/model_baseline_conflicts.csv",
    "hsmm_lifecycle_watch": "watchlists/hsmm_lifecycle_watch.csv",
    "stage03v_readiness_watch": "watchlists/stage03v_readiness_watch.csv",
}


@dataclass(frozen=True)
class ExchangeResult:
    manifest: dict[str, Any]
    output_dir: Path
    archive_dir: Path
    archive_snapshot_dir: Path | None


def load_policy(path: str | Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy_path = Path(path)
    text = policy_path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - JSON-compatible config is the supported path.
            raise ValueError(f"policy is not JSON-compatible and PyYAML is unavailable: {policy_path}") from exc
        payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError(f"policy must be an object: {policy_path}")
    return payload


def validate_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = [
        "index_id",
        "exchange_repo_full_name",
        "local_output_dir",
        "local_archive_dir",
        "exchange_latest_dir",
        "exchange_archive_dir",
        "max_snapshot_rows",
        "max_watchlist_rows",
        "not_trading_output",
        "bundle_version",
        "allowed_output_files",
        "forbidden_terms",
    ]
    for key in required:
        if key not in policy:
            errors.append(f"missing_policy_key:{key}")
    if policy.get("index_id") != INDEX_ID:
        errors.append("index_id_mismatch")
    for key in [
        "include_raw_prices",
        "include_raw_ohlcv",
        "include_full_matrices",
        "include_holdout_performance",
        "include_private_paths",
    ]:
        if bool(policy.get(key, True)):
            errors.append(f"unsafe_policy_flag:{key}")
    if str(policy.get("not_trading_output")) != "yes":
        errors.append("not_trading_output_not_yes")
    allowed = set(policy.get("allowed_output_files", []))
    expected = {
        "signal_bundle.md",
        "signal_bundle.json",
        "signal_snapshot_lite.csv",
        "provenance.json",
        "prompt_template.md",
        "exchange_manifest.json",
        *WATCHLIST_FILES.values(),
    }
    missing_allowed = sorted(expected - allowed)
    if missing_allowed:
        errors.append(f"allowed_output_files_missing:{','.join(missing_allowed)}")
    if int(policy.get("max_snapshot_rows", 0) or 0) <= 0:
        errors.append("max_snapshot_rows_must_be_positive")
    if int(policy.get("max_watchlist_rows", 0) or 0) <= 0:
        errors.append("max_watchlist_rows_must_be_positive")
    return errors


def _json_sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_sanitize(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_json_sanitize(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_sanitize(value.item())
    if value is None:
        return None
    try:
        if pd.isna(value):
            return UNAVAILABLE
    except Exception:
        pass
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_sanitize(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_numeric(value: Any) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) else float("nan")


def _safe_text(value: Any) -> str:
    if value is None:
        return UNAVAILABLE
    try:
        if pd.isna(value):
            return UNAVAILABLE
    except Exception:
        pass
    text = str(value).strip()
    return text if text else UNAVAILABLE


def build_synthetic_signal_snapshot() -> pd.DataFrame:
    dates = pd.date_range("2026-05-01", periods=45, freq="B")
    specs = [
        ("801010", "Agriculture", "industry", 0.035, "RiskOff", 0.72, "late", 0.82, "baseline_high_model_low"),
        ("801020", "Mining", "industry", 0.028, "TrendUp", 0.68, "mature", 0.64, "baseline_low_model_high"),
        ("801030", "Chemicals", "industry", 0.018, "Neutral", 0.54, "early", 0.22, "baseline_low_model_low"),
        ("801040", "Steel", "industry", 0.031, "RiskOff", 0.76, "late", 0.91, "baseline_high_model_low"),
        ("801050", "Electronics", "industry", 0.012, "TrendUp", 0.61, "mature", 0.35, "baseline_available_model_unavailable"),
    ]
    rows: list[dict[str, Any]] = []
    for sector_idx, (sector_id, sector_name, sector_type, amplitude, *_rest) in enumerate(specs):
        base = 100.0 + sector_idx * 3
        for idx, date in enumerate(dates):
            wave = np.sin(idx / 3 + sector_idx) * amplitude
            shock = -amplitude * 1.8 if sector_idx in {0, 3} and idx % 11 == 0 else amplitude * 0.3
            close = base * (1 + 0.002 * idx + wave + shock)
            rows.append(
                {
                    "sector_id": sector_id,
                    "sector_name": sector_name,
                    "sector_type": sector_type,
                    "trade_date": date,
                    "open": close * 0.998,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1000 + idx,
                    "amount": 10000 + idx,
                }
            )
    ohlcv = pd.DataFrame(rows)
    hmm = pd.DataFrame(
        [
            {
                "sector_id": sector_id,
                "state_label": state,
                "prob_trend_up": 0.76 if state == "TrendUp" else 0.12,
                "prob_neutral": 0.65 if state == "Neutral" else 0.11,
                "prob_risk_off": confidence if state == "RiskOff" else 0.18,
                "state_source": "synthetic_causal_cache",
                "recent_state_switch_flag": "yes" if phase == "late" else "no",
            }
            for sector_id, _name, _type, _amp, state, confidence, phase, _exit, _align in specs
        ]
    )
    hsmm = pd.DataFrame(
        [
            {
                "sector_code": sector_id,
                "state_phase": phase,
                "display_state_age_days": 42 if phase == "late" else 18,
                "display_age_bucket": "late" if phase == "late" else "mid",
                "duration_percentile_display": 0.89 if phase == "late" else 0.45,
                "exit_tendency_5d": exit_value * 0.6,
                "exit_tendency_10d": exit_value,
                "exit_tendency_20d": min(exit_value + 0.05, 0.99),
                "probability_display_policy": "display_bucket_only",
            }
            for sector_id, _name, _type, _amp, _state, _confidence, phase, exit_value, _align in specs
        ]
    )
    snapshot = build_signal_panel_snapshot_from_frames(ohlcv, hmm_context=hmm, hsmm_context=hsmm)
    for sector_id, _name, _type, _amp, _state, _confidence, _phase, _exit, align in specs:
        snapshot.loc[snapshot["sector_id"].eq(sector_id), "model_baseline_alignment_status"] = align
    return snapshot


def build_source_snapshot(args: argparse.Namespace) -> tuple[pd.DataFrame, str]:
    if args.synthetic:
        return build_synthetic_signal_snapshot(), "synthetic_signal_panel_snapshot"
    storage = DuckDBStorage(args.db) if args.db else DuckDBStorage()
    return build_signal_panel_snapshot(storage=storage, signal_date=args.signal_date), "src.signals.signal_panel_snapshot"


def build_lite_snapshot(snapshot: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    work = snapshot.copy()
    for column in ALLOWED_LITE_COLUMNS:
        if column not in work.columns:
            work[column] = UNAVAILABLE
    sort_cols = [col for col in ["volatility_percentile_cs", "sector_id"] if col in work.columns]
    if "volatility_percentile_cs" in sort_cols:
        work["_sort_vol"] = pd.to_numeric(work["volatility_percentile_cs"], errors="coerce").fillna(-1)
        work = work.sort_values(["_sort_vol", "sector_id"], ascending=[False, True])
        work = work.drop(columns=["_sort_vol"])
    elif sort_cols:
        work = work.sort_values(sort_cols)
    lite = work[ALLOWED_LITE_COLUMNS].head(max_rows).copy()
    lite["not_trading_output"] = "yes"
    return lite.fillna(UNAVAILABLE)


def _with_watch_reason(df: pd.DataFrame, reason: str, max_rows: int) -> pd.DataFrame:
    out = df.head(max_rows).copy()
    out.insert(0, "watch_reason", reason)
    out["not_trading_output"] = "yes"
    return out.fillna(UNAVAILABLE)


def build_watchlists(lite: pd.DataFrame, max_rows: int) -> dict[str, pd.DataFrame]:
    vol = pd.to_numeric(lite["volatility_percentile_cs"], errors="coerce")
    high_baseline = lite[lite["volatility_band"].astype(str).isin({"high", "extreme"}) | (vol >= 0.80)]
    conflicts = lite[
        lite["model_baseline_alignment_status"].astype(str).isin(
            {"baseline_high_model_low", "baseline_low_model_high"}
        )
    ]
    exit10 = pd.to_numeric(lite["exit_tendency_10d"], errors="coerce")
    exit20 = pd.to_numeric(lite["exit_tendency_20d"], errors="coerce")
    hsmm_watch = lite[lite["hsmm_state_phase"].astype(str).eq("late") | (exit10 >= 0.60) | (exit20 >= 0.65)]
    readiness_text = (
        lite["stage03v_readiness_summary"].astype(str)
        + " "
        + lite["stage03v_probability_source_status"].astype(str)
        + " "
        + lite["stage03v_probability_display_status"].astype(str)
    )
    readiness_watch = lite[
        readiness_text.str.contains("usable_probability_candidate|probability|unavailable", case=False, na=False)
    ]
    return {
        "high_baseline_risk": _with_watch_reason(high_baseline, "baseline volatility risk is high or top-percentile", max_rows),
        "model_baseline_conflicts": _with_watch_reason(conflicts, "baseline and model overlay disagree", max_rows),
        "hsmm_lifecycle_watch": _with_watch_reason(hsmm_watch, "HSMM lifecycle is late or exit tendency is elevated", max_rows),
        "stage03v_readiness_watch": _with_watch_reason(readiness_watch, "Stage03V probability/readiness source needs review", max_rows),
    }


def summarize_bundle(lite: pd.DataFrame, watchlists: dict[str, pd.DataFrame]) -> dict[str, Any]:
    signal_date = UNAVAILABLE if lite.empty else _safe_text(lite["signal_date"].max())
    band_counts = lite["volatility_band"].astype(str).value_counts().to_dict() if "volatility_band" in lite else {}
    alignment_counts = (
        lite["model_baseline_alignment_status"].astype(str).value_counts().to_dict()
        if "model_baseline_alignment_status" in lite
        else {}
    )
    return {
        "signal_date": signal_date,
        "snapshot_rows": int(len(lite)),
        "data_freshness_status_counts": lite["data_freshness_status"].astype(str).value_counts().to_dict()
        if "data_freshness_status" in lite
        else {},
        "volatility_band_counts": band_counts,
        "model_baseline_alignment_counts": alignment_counts,
        "stage03v_probability_source_status_counts": lite["stage03v_probability_source_status"].astype(str).value_counts().to_dict()
        if "stage03v_probability_source_status" in lite
        else {},
        "watchlist_rows": {name: int(len(df)) for name, df in watchlists.items()},
        "baseline_first": "yes",
        "not_trading_output": "yes",
    }


def build_provenance(policy_path: Path, signal_snapshot_source: str) -> dict[str, Any]:
    return {
        "source_repo": SOURCE_REPO,
        "exchange_repo": "timoktim/hmm-info-exchange",
        "signal_panel_contract_path": "reports/stage03v/phase2_signal_panel_contract.json",
        "stage03v_closeout_report_path": STAGE03V_CLOSEOUT_REPORT_PATH.relative_to(Path.cwd()).as_posix(),
        "stage03v_phase2_handoff_path": STAGE03V_HANDOFF_PATH.relative_to(Path.cwd()).as_posix(),
        "stage03v_final_gate_v2_path": STAGE03V_FINAL_GATE_V2_PATH.relative_to(Path.cwd()).as_posix(),
        "stage03v_invalidated_artifact_registry_path": STAGE03V_INVALIDATED_REGISTRY_PATH.relative_to(Path.cwd()).as_posix(),
        "signal_snapshot_source": signal_snapshot_source,
        "accepted_signal_source_paths": ACCEPTED_SIGNAL_SOURCE_PATHS,
        "invalidated_signal_sources_forbidden": list(INVALIDATED_SIGNAL_SOURCE_FORBIDDEN),
        "export_policy_path": policy_path.as_posix(),
        "not_trading_output": "yes",
        "invalidated_artifact_policy": "old WP4-WP6 and old WP7-v1 artifacts are not signal evidence",
    }


def _policy_public_summary(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "index_id": policy.get("index_id"),
        "bundle_version": policy.get("bundle_version"),
        "max_snapshot_rows": policy.get("max_snapshot_rows"),
        "max_watchlist_rows": policy.get("max_watchlist_rows"),
        "include_raw_prices": policy.get("include_raw_prices"),
        "include_raw_ohlcv": policy.get("include_raw_ohlcv"),
        "include_full_matrices": policy.get("include_full_matrices"),
        "include_holdout_performance": policy.get("include_holdout_performance"),
        "include_private_paths": policy.get("include_private_paths"),
        "not_trading_output": policy.get("not_trading_output"),
    }


def build_bundle_json(
    *,
    generated_at: str,
    policy: dict[str, Any],
    lite: pd.DataFrame,
    watchlists: dict[str, pd.DataFrame],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    summary = summarize_bundle(lite, watchlists)
    return {
        "index_id": INDEX_ID,
        "bundle_version": policy["bundle_version"],
        "generated_at": generated_at,
        "signal_date": summary["signal_date"],
        "source_repo": SOURCE_REPO,
        "exchange_repo": policy["exchange_repo_full_name"],
        "not_trading_output": "yes",
        "not_trading_output_warning": WARNING_TEXT,
        "summary": summary,
        "watchlists": {name: df.to_dict(orient="records") for name, df in watchlists.items()},
        "provenance": provenance,
        "policy": _policy_public_summary(policy),
        "boundary_flags": {
            "openai_api_called": "no",
            "external_upload_automatic": "no",
            "credentials_stored": "no",
            "raw_duckdb_exported": "no",
            "full_matrices_exported": "no",
            "holdout_consumed": "no",
            "stage03v_artifacts_modified": "no",
            "model_training_recalibration": "no",
            "trading_or_decision_output": "no",
            "private_paths_leaked": "no",
            "invalidated_artifacts_used_as_evidence": "no",
        },
    }


def build_bundle_markdown(bundle: dict[str, Any], lite: pd.DataFrame) -> str:
    summary = bundle["summary"]
    watchlists = summary["watchlist_rows"]
    top_risk = lite.head(10)[
        [
            "sector_id",
            "sector_name",
            "volatility_band",
            "volatility_percentile_cs",
            "hmm_state_label",
            "hsmm_state_phase",
            "model_baseline_alignment_status",
        ]
    ]
    table_columns = list(top_risk.columns)
    table_lines = ["|" + "|".join(table_columns) + "|", "|" + "|".join(["---"] * len(table_columns)) + "|"]
    for record in top_risk.to_dict(orient="records"):
        table_lines.append("|" + "|".join(_safe_text(record.get(column)).replace("|", "/") for column in table_columns) + "|")
    lines = [
        "# HMM GPT Information Exchange Bundle",
        "",
        f"- generated_at: {bundle['generated_at']}",
        f"- signal_date: {bundle['signal_date']}",
        f"- source_repo: {bundle['source_repo']}",
        f"- exchange_repo: {bundle['exchange_repo']}",
        f"- not_trading_output: {bundle['not_trading_output']}",
        "",
        f"> {WARNING_TEXT}",
        "",
        "## Data Freshness",
        "",
        f"- status_counts: {summary['data_freshness_status_counts']}",
        f"- snapshot_rows: {summary['snapshot_rows']}",
        "",
        "## Baseline-First Risk Summary",
        "",
        f"- volatility_band_counts: {summary['volatility_band_counts']}",
        f"- model_baseline_alignment_counts: {summary['model_baseline_alignment_counts']}",
        "",
        "## High Baseline Risk Sectors",
        "",
        "\n".join(table_lines),
        "",
        "## Watchlists",
        "",
    ]
    for name, count in watchlists.items():
        lines.append(f"- {name}: {count} rows")
    lines.extend(
        [
            "",
            "## Stage03V Readiness / Probability Source Summary",
            "",
            f"- source_status_counts: {summary['stage03v_probability_source_status_counts']}",
            "- Numeric probabilities are included only when the current per-entity source is available.",
            "",
            "## External-Search Questions For GPT Pro",
            "",
            "- Check recent public explanations for highlighted sector moves and separate public facts from model evidence.",
            "- Identify macro, policy, earnings, commodity, or liquidity context that may explain high baseline-risk sectors.",
            "- State uncertainty and list manual review questions before drawing any conclusion.",
            "",
            "## Provenance",
            "",
            f"- signal_snapshot_source: {bundle['provenance']['signal_snapshot_source']}",
            f"- signal_panel_contract_path: {bundle['provenance']['signal_panel_contract_path']}",
            f"- stage03v_final_gate_v2_path: {bundle['provenance']['stage03v_final_gate_v2_path']}",
            "",
            "## Invalidated-Artifact Warning",
            "",
            f"- {INVALIDATED_ARTIFACT_WARNING}",
            "",
            "## Manual-Review Checklist",
            "",
            "- Verify the data freshness date against the intended review date.",
            "- Compare baseline volatility evidence with HMM/HSMM overlays.",
            "- Treat Stage03V probability fields as unavailable unless the bundle says a current per-entity source exists.",
            "- Keep final judgment with the human reviewer.",
        ]
    )
    return "\n".join(lines) + "\n"


def prompt_template_text() -> str:
    return """# GPT Pro Signal Bundle Review Prompt

Read the attached HMM GPT information-exchange bundle and its watchlists.

Constraints:
- Separate model evidence, external public information, and your own inference.
- Use web/search to check recent public explanations for highlighted sectors.
- State uncertainty and cite what is model-derived versus externally observed.
- Do not output trading, sizing, buy/sell, recommendation, execution, or portfolio-action advice.
- Produce manual-review questions for the human reviewer.

Required structure:
1. Data freshness and provenance check.
2. Baseline-first risk summary.
3. Model-baseline conflicts worth manual review.
4. HSMM lifecycle observations.
5. Stage03V probability/readiness limitations.
6. External context to verify with public sources.
7. Manual-review questions.
"""


def write_local_outputs(
    *,
    output_dir: Path,
    archive_dir: Path,
    timestamp: str,
    lite: pd.DataFrame,
    watchlists: dict[str, pd.DataFrame],
    bundle: dict[str, Any],
    provenance: dict[str, Any],
    manifest: dict[str, Any],
    write_archive: bool = True,
) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "watchlists").mkdir(parents=True, exist_ok=True)
    lite.to_csv(output_dir / "signal_snapshot_lite.csv", index=False)
    for name, df in watchlists.items():
        df.to_csv(output_dir / WATCHLIST_FILES[name], index=False)
    (output_dir / "signal_bundle.md").write_text(build_bundle_markdown(bundle, lite), encoding="utf-8")
    _write_json(output_dir / "signal_bundle.json", bundle)
    _write_json(output_dir / "provenance.json", provenance)
    (output_dir / "prompt_template.md").write_text(prompt_template_text(), encoding="utf-8")
    _write_json(output_dir / "exchange_manifest.json", manifest)

    if not write_archive:
        return None
    archive_snapshot_dir = archive_dir / timestamp
    if archive_snapshot_dir.exists():
        shutil.rmtree(archive_snapshot_dir)
    shutil.copytree(output_dir, archive_snapshot_dir)
    return archive_snapshot_dir


def _copy_exchange_outputs(output_dir: Path, exchange_dir: Path, policy: dict[str, Any], timestamp: str, bootstrap: bool) -> str:
    if not exchange_dir.exists():
        if bootstrap:
            exchange_dir.mkdir(parents=True, exist_ok=True)
        else:
            return "skipped_exchange_repo_unavailable"
    non_git_entries = [entry for entry in exchange_dir.iterdir() if entry.name != ".git"]
    if bootstrap and not (exchange_dir / "README.md").exists() and not non_git_entries:
        (exchange_dir / "README.md").write_text(
            "# HMM Info Exchange\n\nPrivate redacted signal bundles for human GPT Pro review.\n",
            encoding="utf-8",
        )
    latest = exchange_dir / str(policy["exchange_latest_dir"])
    archive = exchange_dir / str(policy["exchange_archive_dir"]) / timestamp
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(output_dir, latest)
    if archive.exists():
        shutil.rmtree(archive)
    shutil.copytree(output_dir, archive)
    return "pass"


def _exchange_sync_status(exchange_dir: Path | None, bootstrap: bool) -> str:
    if exchange_dir is None:
        return "skipped_exchange_repo_unavailable"
    if exchange_dir.exists() or bootstrap:
        return "pass"
    return "skipped_exchange_repo_unavailable"


def _public_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except Exception:
        return "<external-path-redacted>"


def _rewrite_status_outputs(
    *,
    output_dir: Path,
    archive_snapshot_dir: Path | None,
    lite: pd.DataFrame,
    bundle: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    bundle["manifest_summary"] = {
        "exchange_repo_status": manifest["exchange_repo_status"],
        "sync_status": manifest["sync_status"],
        "snapshot_rows": manifest["snapshot_rows"],
        "watchlists_generated": manifest["watchlists_generated"],
    }
    (output_dir / "signal_bundle.md").write_text(build_bundle_markdown(bundle, lite), encoding="utf-8")
    _write_json(output_dir / "signal_bundle.json", bundle)
    _write_json(output_dir / "exchange_manifest.json", manifest)
    if archive_snapshot_dir is not None:
        (archive_snapshot_dir / "signal_bundle.md").write_text(build_bundle_markdown(bundle, lite), encoding="utf-8")
        _write_json(archive_snapshot_dir / "signal_bundle.json", bundle)
        _write_json(archive_snapshot_dir / "exchange_manifest.json", manifest)


def _git_commit(exchange_dir: Path, message: str) -> str:
    git_dir = exchange_dir / ".git"
    if not git_dir.exists():
        return "failed_exchange_dir_not_git_repo"
    add_paths = [name for name in ["README.md", "latest", "archive"] if (exchange_dir / name).exists()]
    if not add_paths:
        return "skipped_no_exchange_files"
    subprocess.run(["git", "-C", str(exchange_dir), "add", *add_paths], check=True)
    status = subprocess.run(["git", "-C", str(exchange_dir), "status", "--porcelain"], check=True, text=True, capture_output=True)
    if not status.stdout.strip():
        return "skipped_no_changes"
    subprocess.run(["git", "-C", str(exchange_dir), "commit", "-m", message], check=True)
    return "pass"


def _git_push(exchange_dir: Path) -> str:
    subprocess.run(["git", "-C", str(exchange_dir), "push"], check=True)
    return "pass"


def _assert_public_safe(paths: list[Path], forbidden_terms: list[str]) -> None:
    required_warning_exemptions = {"buy/sell"}
    for path in paths:
        if not path.exists() or path.is_dir():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for term in forbidden_terms:
            if term in required_warning_exemptions:
                continue
            if term and term in text:
                raise ValueError(f"forbidden term found in {path.as_posix()}: {term}")


def run_export(args: argparse.Namespace) -> ExchangeResult:
    policy_path = Path(args.policy)
    policy = load_policy(policy_path)
    errors = validate_policy(policy)
    if errors:
        raise ValueError("; ".join(errors))
    if args.push and not args.commit:
        raise ValueError("--push requires --commit")
    if args.commit and not args.write_exchange:
        raise ValueError("--commit requires --write-exchange")

    max_rows = int(args.max_rows or policy["max_snapshot_rows"])
    max_watchlist_rows = int(args.max_watchlist_rows or policy["max_watchlist_rows"])
    output_dir = Path(args.output_dir or policy["local_output_dir"])
    archive_dir = Path(args.archive_dir or policy["local_archive_dir"])
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    generated_at = datetime.now(timezone.utc).isoformat()

    snapshot, snapshot_source = build_source_snapshot(args)
    schema_issues = validate_snapshot_schema(snapshot)
    if schema_issues:
        raise ValueError(f"signal snapshot schema invalid: {schema_issues}")
    lite = build_lite_snapshot(snapshot, max_rows)
    watchlists = build_watchlists(lite, max_watchlist_rows)
    provenance = build_provenance(policy_path, snapshot_source)
    bundle = build_bundle_json(
        generated_at=generated_at,
        policy=policy,
        lite=lite,
        watchlists=watchlists,
        provenance=provenance,
    )

    exchange_dir_arg = args.exchange_dir or os.environ.get("HMM_INFO_EXCHANGE_DIR")
    exchange_dir = Path(exchange_dir_arg) if exchange_dir_arg else None
    exchange_repo_status = "unavailable_or_not_configured"
    sync_status = "skipped_exchange_repo_unavailable"
    exchange_workspace_export = "skipped"
    commit_status = "not_requested"
    push_status = "not_requested"
    if exchange_dir is not None:
        exchange_repo_status = "provided_local_workspace"
        if args.write_exchange:
            sync_status = _exchange_sync_status(exchange_dir, args.bootstrap_exchange_repo)
            exchange_workspace_export = "pass" if sync_status == "pass" else "skipped"
            if sync_status == "pass" and args.commit:
                commit_status = "requested"
            if sync_status == "pass" and args.push:
                push_status = "requested"
        else:
            sync_status = "skipped_write_exchange_not_requested"
    manifest = {
        "index_id": INDEX_ID,
        "bundle_version": policy["bundle_version"],
        "generated_at": generated_at,
        "source_repo": SOURCE_REPO,
        "exchange_repo": policy["exchange_repo_full_name"],
        "exchange_repo_status": exchange_repo_status,
        "sync_status": sync_status,
        "exchange_workspace_export": exchange_workspace_export,
        "commit_status": commit_status,
        "push_status": push_status,
        "push_executed": "yes" if push_status == "pass" else "no",
        "output_dir": _public_path(output_dir),
        "archive_dir": _public_path(archive_dir),
        "snapshot_rows": int(len(lite)),
        "watchlists_generated": len(watchlists),
        "watchlist_rows": {name: int(len(df)) for name, df in watchlists.items()},
        "output_files": list(policy["allowed_output_files"]),
        "not_trading_output": "yes",
        "boundary_flags": bundle["boundary_flags"],
    }
    bundle["manifest_summary"] = {
        "exchange_repo_status": exchange_repo_status,
        "sync_status": sync_status,
        "snapshot_rows": int(len(lite)),
        "watchlists_generated": len(watchlists),
    }
    archive_snapshot_dir = write_local_outputs(
        output_dir=output_dir,
        archive_dir=archive_dir,
        timestamp=timestamp,
        lite=lite,
        watchlists=watchlists,
        bundle=bundle,
        provenance=provenance,
        manifest=manifest,
        write_archive=True,
    )
    if exchange_dir is not None and args.write_exchange and sync_status == "pass":
        sync_status = _copy_exchange_outputs(output_dir, exchange_dir, policy, timestamp, args.bootstrap_exchange_repo)
        manifest["sync_status"] = sync_status
        manifest["exchange_workspace_export"] = "pass" if sync_status == "pass" else "skipped"
        if args.commit and sync_status == "pass":
            manifest["commit_status"] = _git_commit(exchange_dir, f"Update HMM info exchange bundle {timestamp}")
        if args.push and manifest["commit_status"] in {"pass", "skipped_no_changes"}:
            manifest["push_status"] = _git_push(exchange_dir)
            manifest["push_executed"] = "yes" if manifest["push_status"] == "pass" else "no"

    generated_paths = [
        output_dir / "signal_bundle.md",
        output_dir / "signal_bundle.json",
        output_dir / "signal_snapshot_lite.csv",
        output_dir / "provenance.json",
        output_dir / "prompt_template.md",
        output_dir / "exchange_manifest.json",
        *[output_dir / rel for rel in WATCHLIST_FILES.values()],
    ]
    _assert_public_safe(generated_paths, list(policy.get("forbidden_terms", [])))
    return ExchangeResult(manifest=manifest, output_dir=output_dir, archive_dir=archive_dir, archive_snapshot_dir=archive_snapshot_dir)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a redacted GPT information-exchange signal bundle")
    parser.add_argument("--db", default=None)
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--archive-dir", default=None)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--max-watchlist-rows", type=int, default=None)
    parser.add_argument("--signal-date", default=None)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--exchange-dir", default=None)
    parser.add_argument("--bootstrap-exchange-repo", action="store_true")
    parser.add_argument("--write-exchange", action="store_true")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.no_push:
        args.push = False
    try:
        result = run_export(args)
    except Exception as exc:
        print(f"GPT_INFO_EXCHANGE_EXPORT=fail error={type(exc).__name__}:{exc}")
        return 2
    manifest = result.manifest
    print(
        "GPT_INFO_EXCHANGE_EXPORT=pass "
        f"output_dir={result.output_dir.as_posix()} "
        f"exchange_repo_status={manifest['exchange_repo_status']} "
        f"sync_status={manifest['sync_status']} "
        f"snapshot_rows={manifest['snapshot_rows']} "
        f"watchlists={manifest['watchlists_generated']} "
        f"not_trading_output=yes "
        f"push={manifest['push_executed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
