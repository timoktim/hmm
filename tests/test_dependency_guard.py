from __future__ import annotations

import pytest

from src.utils.dependency_guard import (
    CORE_DEPENDENCY_SPECS,
    DependencyGuardError,
    build_dependency_report,
    check_dependency_versions,
)


def _supported_versions() -> dict[str, str]:
    return {spec.package: spec.minimum for spec in CORE_DEPENDENCY_SPECS}


def test_dependency_guard_accepts_supported_core_versions() -> None:
    report = check_dependency_versions(_supported_versions())

    assert report.ok
    assert {status.package for status in report.statuses} == {spec.package for spec in CORE_DEPENDENCY_SPECS}


def test_dependency_version_outside_allowed_range_fails_guard() -> None:
    versions = _supported_versions()
    versions["numpy"] = "3.0.0"

    with pytest.raises(DependencyGuardError, match="numpy=3.0.0"):
        check_dependency_versions(versions)


def test_missing_dependency_is_reported_without_import_side_effects() -> None:
    versions = _supported_versions()
    versions.pop("duckdb")

    report = build_dependency_report(versions)

    assert not report.ok
    missing = [status for status in report.statuses if status.package == "duckdb"]
    assert len(missing) == 1
    assert missing[0].reason == "missing"
