#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="$PYTHON_BIN"
elif [[ -n "${PYTHON:-}" ]]; then
  PYTHON_BIN="$PYTHON"
elif [[ -x .venv/bin/python ]]; then
  PYTHON_BIN=".venv/bin/python"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "PRIVATE_PATH_HYGIENE=fail"
  echo "No python interpreter found. Set PYTHON_BIN/PYTHON or create .venv/bin/python."
  exit 2
fi

"$PYTHON_BIN" - "$@" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path.cwd()
DEFAULT_TARGETS = [ROOT / "docs", ROOT / "reports"]
TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".csv", ".txt", ".yml", ".yaml"}
EXEMPT_PREFIXES = {
    "docs/work_packages/",
}

RULES = [
    ("mac_user_path", re.compile(r"/Users/[^\s`\"'<>]*")),
    ("mac_volume_path", re.compile(r"/Volumes/[^\s`\"'<>]*")),
    ("linux_home_path", re.compile(r"/home/[^\s`\"'<>]*")),
    ("codex_worktree_path", re.compile(r"\.codex_worktrees")),
    ("local_project_name", re.compile(r"HMM高阶分析器")),
    (
        "absolute_duckdb_path",
        re.compile(r"(?<![\w.-])/(?!absolute/path/to/)[^\s`\"'<>]*\.duckdb(?:\.wal)?"),
    ),
]


def rel_name(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def is_exempt(path: Path) -> bool:
    name = rel_name(path)
    return any(name.startswith(prefix) for prefix in EXEMPT_PREFIXES)


def iter_files(targets: list[Path]) -> list[Path]:
    files: list[Path] = []
    for target in targets:
        if not target.exists():
            continue
        if target.is_file():
            files.append(target)
            continue
        for path in sorted(target.rglob("*")):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                files.append(path)
    return files


def allowed_policy_placeholder(line: str) -> bool:
    return "/absolute/path/to/a_share_hmm.duckdb" in line


def scan_file(path: Path) -> list[tuple[str, int, str, str]]:
    if is_exempt(path):
        return []
    findings: list[tuple[str, int, str, str]] = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if allowed_policy_placeholder(line):
            continue
        for rule_name, pattern in RULES:
            if pattern.search(line):
                findings.append((rel_name(path), line_number, rule_name, line.strip()))
    return findings


targets = [Path(arg) for arg in sys.argv[1:]] or DEFAULT_TARGETS
files = iter_files(targets)
findings = [item for path in files for item in scan_file(path)]

if findings:
    print("PRIVATE_PATH_HYGIENE=fail")
    for path, line_number, rule_name, snippet in findings:
        print(f"{path}:{line_number}: {rule_name}: {snippet[:220]}")
    raise SystemExit(1)

print(f"PRIVATE_PATH_HYGIENE=pass scanned_files={len(files)}")
PY
