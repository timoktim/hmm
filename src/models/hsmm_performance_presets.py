from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_PRESET_CONFIG_PATH = Path("configs/hsmm_performance_presets_v1.yaml")
REQUIRED_PRESETS = ("fast_maintenance", "standard_maintenance", "full_maintenance")
FORBIDDEN_VITERBI_FLAGS = (
    "approximate_viterbi",
    "pruned_viterbi",
    "approximate_decode",
    "pruned_decode",
)


@dataclass(frozen=True)
class HSMMPerformancePreset:
    name: str
    n_iter: int
    max_duration: int
    train_frequency: str
    snapshot_decode_mode: str
    hsmm_engine: str
    n_jobs: int | str
    fit_n_jobs: int | str
    sequence_chunk_size: int
    fit_sequence_chunk_size: int
    profile_only: bool
    usage: str

    @classmethod
    def from_payload(cls, name: str, payload: dict[str, Any]) -> "HSMMPerformancePreset":
        return cls(
            name=name,
            n_iter=int(payload["n_iter"]),
            max_duration=int(payload["max_duration"]),
            train_frequency=str(payload["train_frequency"]),
            snapshot_decode_mode=str(payload["snapshot_decode_mode"]),
            hsmm_engine=str(payload.get("hsmm_engine", "auto")),
            n_jobs=payload.get("n_jobs", "auto"),
            fit_n_jobs=payload.get("fit_n_jobs", payload.get("n_jobs", "auto")),
            sequence_chunk_size=int(payload.get("sequence_chunk_size", 32)),
            fit_sequence_chunk_size=int(payload.get("fit_sequence_chunk_size", payload.get("sequence_chunk_size", 32))),
            profile_only=bool(payload.get("profile_only", False)),
            usage=str(payload.get("usage", "")),
        )

    def walk_forward_overrides(self) -> dict[str, object]:
        return {
            "n_iter": self.n_iter,
            "max_duration": self.max_duration,
            "train_frequency": self.train_frequency,
            "snapshot_decode_mode": self.snapshot_decode_mode,
            "hsmm_engine": self.hsmm_engine,
            "n_jobs": self.n_jobs,
            "fit_n_jobs": self.fit_n_jobs,
            "sector_chunk_size": self.sequence_chunk_size,
            "fit_sequence_chunk_size": self.fit_sequence_chunk_size,
            "profile_only": self.profile_only,
        }


def _read_config_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_hsmm_performance_preset_config(path: str | Path = DEFAULT_PRESET_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    text = _read_config_text(config_path)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-untyped]
        except Exception as exc:  # pragma: no cover - JSON-compatible config is the CI path.
            raise ValueError(f"Preset config is not JSON-compatible and PyYAML is unavailable: {config_path}") from exc
        payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError(f"Preset config must be an object: {config_path}")
    return payload


def load_hsmm_performance_presets(path: str | Path = DEFAULT_PRESET_CONFIG_PATH) -> dict[str, HSMMPerformancePreset]:
    payload = load_hsmm_performance_preset_config(path)
    errors = validate_hsmm_performance_preset_config(payload)
    if errors:
        raise ValueError("; ".join(errors))
    presets = payload["presets"]
    return {name: HSMMPerformancePreset.from_payload(name, dict(presets[name])) for name in REQUIRED_PRESETS}


def validate_hsmm_performance_preset_config(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    presets = payload.get("presets")
    if not isinstance(presets, dict):
        return ["missing presets object"]

    missing = [name for name in REQUIRED_PRESETS if name not in presets]
    if missing:
        errors.append(f"missing required presets: {', '.join(missing)}")

    parsed: dict[str, HSMMPerformancePreset] = {}
    for name in REQUIRED_PRESETS:
        raw = presets.get(name)
        if not isinstance(raw, dict):
            continue
        for key in ("n_iter", "max_duration", "train_frequency", "snapshot_decode_mode"):
            if key not in raw:
                errors.append(f"{name} missing {key}")
        for flag in FORBIDDEN_VITERBI_FLAGS:
            if bool(raw.get(flag, False)):
                errors.append(f"{name} enables forbidden {flag}")
        if str(raw.get("snapshot_decode_mode", "")).lower() != "prefix":
            errors.append(f"{name} must use prefix snapshot_decode_mode")
        if str(raw.get("hsmm_probability_semantics", "")).lower() != "unchanged":
            errors.append(f"{name} must keep hsmm_probability_semantics unchanged")
        if str(raw.get("lifecycle_probability_semantics", "")).lower() != "unchanged":
            errors.append(f"{name} must keep lifecycle_probability_semantics unchanged")
        if str(raw.get("readiness_policy", "")).lower() != "unchanged":
            errors.append(f"{name} must keep readiness_policy unchanged")
        try:
            preset = HSMMPerformancePreset.from_payload(name, raw)
        except Exception as exc:
            errors.append(f"{name} invalid payload: {exc}")
            continue
        if preset.n_iter <= 0:
            errors.append(f"{name} n_iter must be positive")
        if preset.max_duration < 2:
            errors.append(f"{name} max_duration must be >= 2")
        if preset.train_frequency != "monthly":
            errors.append(f"{name} train_frequency must remain monthly")
        parsed[name] = preset

    fast = parsed.get("fast_maintenance")
    standard = parsed.get("standard_maintenance")
    full = parsed.get("full_maintenance")
    if fast and not (8 <= fast.n_iter <= 10):
        errors.append("fast_maintenance n_iter must be 8 to 10")
    if fast and fast.max_duration != 40:
        errors.append("fast_maintenance max_duration must be 40")
    if standard and standard.n_iter != 20:
        errors.append("standard_maintenance n_iter must be 20")
    if standard and standard.max_duration != 60:
        errors.append("standard_maintenance max_duration must be 60")
    if fast and standard:
        if fast.n_iter > standard.n_iter:
            errors.append("fast_maintenance n_iter must not exceed standard_maintenance")
        if fast.max_duration > standard.max_duration:
            errors.append("fast_maintenance max_duration must not exceed standard_maintenance")
    if standard and full:
        if full.n_iter < standard.n_iter:
            errors.append("full_maintenance n_iter must be at least standard_maintenance")
        if full.max_duration < standard.max_duration:
            errors.append("full_maintenance max_duration must be at least standard_maintenance")
        full_raw = dict(presets.get("full_maintenance", {}))
        if not bool(full_raw.get("explicit_maintenance_window_required", False)):
            errors.append("full_maintenance must require an explicit maintenance window")

    return errors


def preset_summary(path: str | Path = DEFAULT_PRESET_CONFIG_PATH) -> dict[str, dict[str, object]]:
    return {name: preset.walk_forward_overrides() for name, preset in load_hsmm_performance_presets(path).items()}
