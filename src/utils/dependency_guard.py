from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from importlib import metadata
from typing import Mapping, Sequence

import numpy as np


class DependencyGuardError(RuntimeError):
    """Raised when an installed core dependency is outside the supported range."""


class HMMPrivateAPIError(RuntimeError):
    """Raised when hmmlearn private APIs required by filtered inference are unavailable."""


@dataclass(frozen=True)
class DependencySpec:
    package: str
    minimum: str
    maximum_exclusive: str


@dataclass(frozen=True)
class DependencyStatus:
    package: str
    installed_version: str | None
    minimum: str
    maximum_exclusive: str
    ok: bool
    reason: str


@dataclass(frozen=True)
class DependencyReport:
    ok: bool
    statuses: tuple[DependencyStatus, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "statuses": [asdict(status) for status in self.statuses],
        }


CORE_DEPENDENCY_SPECS: tuple[DependencySpec, ...] = (
    DependencySpec("pandas", "2.1", "4.0"),
    DependencySpec("numpy", "1.26", "3.0"),
    DependencySpec("scipy", "1.11", "2.0"),
    DependencySpec("hmmlearn", "0.3.2", "0.4"),
    DependencySpec("duckdb", "0.10", "2.0"),
    DependencySpec("streamlit", "1.57.0", "2.0"),
    DependencySpec("akshare", "1.13", "2.0"),
)


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", version.split("+", 1)[0])
    if not parts:
        raise ValueError(f"cannot parse version: {version!r}")
    parsed = tuple(int(part) for part in parts[:4])
    return parsed + (0,) * (4 - len(parsed))


def _version_in_range(version: str, minimum: str, maximum_exclusive: str) -> bool:
    parsed = _version_tuple(version)
    return _version_tuple(minimum) <= parsed < _version_tuple(maximum_exclusive)


def build_dependency_report(
    versions: Mapping[str, str] | None = None,
    specs: Sequence[DependencySpec] = CORE_DEPENDENCY_SPECS,
) -> DependencyReport:
    statuses: list[DependencyStatus] = []
    for spec in specs:
        try:
            installed = versions[spec.package] if versions is not None else metadata.version(spec.package)
        except (KeyError, metadata.PackageNotFoundError):
            statuses.append(
                DependencyStatus(
                    package=spec.package,
                    installed_version=None,
                    minimum=spec.minimum,
                    maximum_exclusive=spec.maximum_exclusive,
                    ok=False,
                    reason="missing",
                )
            )
            continue
        try:
            ok = _version_in_range(str(installed), spec.minimum, spec.maximum_exclusive)
        except ValueError as exc:
            statuses.append(
                DependencyStatus(
                    package=spec.package,
                    installed_version=str(installed),
                    minimum=spec.minimum,
                    maximum_exclusive=spec.maximum_exclusive,
                    ok=False,
                    reason=str(exc),
                )
            )
            continue
        reason = "ok" if ok else f"outside supported range >={spec.minimum},<{spec.maximum_exclusive}"
        statuses.append(
            DependencyStatus(
                package=spec.package,
                installed_version=str(installed),
                minimum=spec.minimum,
                maximum_exclusive=spec.maximum_exclusive,
                ok=ok,
                reason=reason,
            )
        )
    return DependencyReport(ok=all(status.ok for status in statuses), statuses=tuple(statuses))


def check_dependency_versions(
    versions: Mapping[str, str] | None = None,
    specs: Sequence[DependencySpec] = CORE_DEPENDENCY_SPECS,
) -> DependencyReport:
    report = build_dependency_report(versions=versions, specs=specs)
    if not report.ok:
        failures = "; ".join(
            f"{status.package}={status.installed_version or 'missing'} ({status.reason})"
            for status in report.statuses
            if not status.ok
        )
        raise DependencyGuardError(f"core dependency compatibility check failed: {failures}")
    return report


def require_hmmlearn_log_likelihood(model: object, x: np.ndarray) -> np.ndarray:
    compute = getattr(model, "_compute_log_likelihood", None)
    if not callable(compute):
        raise HMMPrivateAPIError(
            "hmmlearn private API _compute_log_likelihood is required for filtered HMM probabilities but is unavailable"
        )
    try:
        log_likelihood = compute(x)
    except TypeError as exc:
        raise HMMPrivateAPIError(
            "hmmlearn private API _compute_log_likelihood could not be called with the expected observation matrix"
        ) from exc
    values = np.asarray(log_likelihood, dtype=float)
    if values.ndim != 2:
        raise HMMPrivateAPIError(
            f"hmmlearn private API _compute_log_likelihood returned {values.ndim} dimensions; expected 2"
        )
    if values.shape[0] != len(x):
        raise HMMPrivateAPIError(
            "hmmlearn private API _compute_log_likelihood returned a row count that does not match observations"
        )
    return values


def monitor_history(model: object) -> tuple[float, ...]:
    monitor = getattr(model, "monitor_", None)
    history = getattr(monitor, "history", None)
    if history is None:
        return ()
    try:
        raw_values = list(history)
    except TypeError:
        return ()
    values: list[float] = []
    for value in raw_values:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(numeric):
            values.append(numeric)
    return tuple(values)


def last_monitor_log_prob(model: object, default: float = float("-inf")) -> float:
    monitor = getattr(model, "monitor_", None)
    history = getattr(monitor, "history", None)
    if history is None:
        return default
    try:
        raw_values = list(history)
    except TypeError:
        return default
    if not raw_values:
        return default
    try:
        value = float(raw_values[-1])
    except (TypeError, ValueError):
        return default
    return value if np.isfinite(value) else default


def monitor_converged(model: object, default: bool = False) -> bool:
    monitor = getattr(model, "monitor_", None)
    value = getattr(monitor, "converged", default)
    if value is None:
        return default
    return bool(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check core dependency compatibility ranges.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()
    report = check_dependency_versions()
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for status in report.statuses:
            print(
                f"{status.package} {status.installed_version}: "
                f">={status.minimum},<{status.maximum_exclusive} {status.reason}"
            )


if __name__ == "__main__":
    main()
