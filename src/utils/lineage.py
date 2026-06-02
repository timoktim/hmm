from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover - optional runtime guard
    np = None  # type: ignore[assignment]

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional runtime guard
    pd = None  # type: ignore[assignment]


VALID_CACHE_STATUS = "completed"


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Return deterministic JSON for lineage payloads."""
    normalized = _normalize_value(payload)
    if not isinstance(normalized, dict):
        raise TypeError("canonical_json expects a mapping payload")
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def hash_payload(payload: Mapping[str, Any], algo: str = "sha256", length: int = 32) -> str:
    if length <= 0:
        raise ValueError("length must be positive")
    digest = hashlib.new(algo)
    digest.update(canonical_json(payload).encode("utf-8"))
    return digest.hexdigest()[:length]


def build_model_lineage_payload(
    *,
    model_family: str,
    model_version: str,
    code_version: str,
    feature_version: str,
    feature_scope_id: str,
    feature_columns: Iterable[str],
    model_params: Mapping[str, Any],
    preprocess_params: Mapping[str, Any],
    train_window_policy: Mapping[str, Any] | str,
    state_date_policy: Mapping[str, Any] | str,
    universe_id: str,
    universe_membership_hash: str,
    custom_basket_membership_hash: str | None,
    data_snapshot_hash: str,
    calendar_hash: str,
    **extra_fields: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model_family": model_family,
        "model_version": model_version,
        "code_version": code_version,
        "feature_version": feature_version,
        "feature_scope_id": feature_scope_id,
        "feature_columns": _stable_feature_columns(feature_columns),
        "model_params": dict(model_params),
        "preprocess_params": dict(preprocess_params),
        "train_window_policy": train_window_policy,
        "state_date_policy": state_date_policy,
        "universe_id": universe_id,
        "universe_membership_hash": universe_membership_hash,
        "custom_basket_membership_hash": custom_basket_membership_hash,
        "data_snapshot_hash": data_snapshot_hash,
        "calendar_hash": calendar_hash,
    }
    for key in sorted(extra_fields):
        payload[key] = extra_fields[key]
    return payload


def is_valid_cache_metadata(cache_metadata: Mapping[str, Any], expected_lineage_hash: str | None = None) -> bool:
    lineage_hash = cache_metadata.get("lineage_hash")
    if not lineage_hash:
        return False
    if expected_lineage_hash is not None and lineage_hash != expected_lineage_hash:
        return False
    return cache_metadata.get("cache_status") == VALID_CACHE_STATUS


def _stable_feature_columns(feature_columns: Iterable[str]) -> list[str]:
    if isinstance(feature_columns, str):
        raise TypeError("feature_columns must be an iterable of column names, not a string")
    if isinstance(feature_columns, (set, frozenset)):
        return sorted(str(column) for column in feature_columns)
    return [str(column) for column in feature_columns]


def _normalize_value(value: Any) -> Any:
    if _is_missing(value):
        return None
    if np is not None and isinstance(value, np.generic):
        return _normalize_value(value.item())
    if pd is not None and isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return _normalize_mapping(value)
    if isinstance(value, (set, frozenset)):
        return _normalize_unordered_iterable(value)
    if isinstance(value, tuple):
        return [_normalize_value(item) for item in value]
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    return value


def _normalize_mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = _normalize_key(key)
        if normalized_key in normalized:
            raise ValueError(f"duplicate normalized JSON key: {normalized_key}")
        normalized[normalized_key] = _normalize_value(item)
    return dict(sorted(normalized.items()))


def _normalize_key(key: Any) -> str:
    normalized = _normalize_value(key)
    if isinstance(normalized, (dict, list)):
        return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return str(normalized)


def _normalize_unordered_iterable(values: set[Any] | frozenset[Any]) -> list[Any]:
    normalized = [_normalize_value(item) for item in values]
    return sorted(
        normalized,
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False),
    )


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if pd is not None:
        try:
            missing = pd.isna(value)
        except (TypeError, ValueError):
            return False
        if isinstance(missing, bool):
            return missing
    if isinstance(value, float):
        return math.isnan(value)
    return False
