from __future__ import annotations

import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RuntimeManifest:
    python_version: str
    platform: str
    git_sha: str
    db_path: str
    report_dir: str | None = None


def get_git_sha(repo_path: str | Path = ".") -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_path),
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def build_runtime_manifest(
    db_path: str,
    report_dir: str | None = None,
    repo_path: str | Path = ".",
) -> RuntimeManifest:
    return RuntimeManifest(
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        git_sha=get_git_sha(repo_path),
        db_path=db_path,
        report_dir=report_dir,
    )


def manifest_as_dict(manifest: RuntimeManifest) -> dict[str, Any]:
    return {
        "python_version": manifest.python_version,
        "platform": manifest.platform,
        "git_sha": manifest.git_sha,
        "db_path": manifest.db_path,
        "report_dir": manifest.report_dir,
    }
