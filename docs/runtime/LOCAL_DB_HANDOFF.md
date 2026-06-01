# LOCAL_DB_HANDOFF

Project: HMM / HSMM analyzer development
Purpose: standard protocol for locating and using the local V0 DuckDB database in Codex tasks

## Canonical rule

The V0 local database is intentionally not committed to GitHub. Every Codex thread that needs data-backed validation must locate or receive the local DuckDB file before running report generation.

Canonical default path inside the repository checkout:

```text
data/db/a_share_hmm.duckdb
```

Canonical environment override:

```bash
export ASHARE_HMM_DB_PATH=/absolute/path/to/a_share_hmm.duckdb
```

Priority order for all Codex tasks:

1. Use the explicit `--db` argument if supplied.
2. Use `$ASHARE_HMM_DB_PATH` if set.
3. Use `data/db/a_share_hmm.duckdb` relative to the repository root.
4. If none exists, stop data-backed validation and report `local_db_missing`.

Do not silently treat missing DB as a passed validation.

## Why the DB is missing from GitHub

The repository intentionally ignores runtime and local data artifacts:

```text
data/db/*.duckdb
data/db/*.wal
data/cache/
data/logs/
data/models/
```

This is correct. Codex must not commit the DuckDB file or WAL file.

## How to provide the DB to a Codex working tree

Preferred method: symlink or copy the existing V0 DB to the canonical path.

```bash
mkdir -p data/db
ln -sf /absolute/path/to/a_share_hmm.duckdb data/db/a_share_hmm.duckdb
```

Copy alternative:

```bash
mkdir -p data/db
cp /absolute/path/to/a_share_hmm.duckdb data/db/a_share_hmm.duckdb
```

If the DB has an active WAL file and the original app was running recently, first stop Streamlit/Python/DuckDB processes. If needed, copy both files:

```text
a_share_hmm.duckdb
a_share_hmm.duckdb.wal
```

The `.wal` file is also ignored by Git and must not be committed.

## How to search for the DB locally

From the repository root, try:

```bash
find .. -name "a_share_hmm.duckdb" 2>/dev/null
```

If necessary on macOS user home:

```bash
find ~ -name "a_share_hmm.duckdb" 2>/dev/null
```

Prefer the DB from the original V0 starting model directory, not a new empty DB.

## Required preflight check

Before running any data-backed validation, Codex must run:

```bash
python - <<'PY'
import os
from pathlib import Path

candidates = []
if os.environ.get("ASHARE_HMM_DB_PATH"):
    candidates.append(Path(os.environ["ASHARE_HMM_DB_PATH"]))
candidates.append(Path("data/db/a_share_hmm.duckdb"))

for path in candidates:
    if path.exists():
        print(f"LOCAL_DB_FOUND={path}")
        raise SystemExit(0)

print("LOCAL_DB_MISSING: set ASHARE_HMM_DB_PATH or place DB at data/db/a_share_hmm.duckdb")
raise SystemExit(2)
PY
```

If the shell does not have `python`, use `.venv/bin/python`.

## Required schema sanity check

After the DB is found, run this read-only check:

```bash
python - <<'PY'
import os
from pathlib import Path
import duckdb

db = Path(os.environ.get("ASHARE_HMM_DB_PATH", "data/db/a_share_hmm.duckdb"))
con = duckdb.connect(str(db), read_only=True)
for table in [
    "model_runs",
    "sector_state_daily",
    "walk_forward_cache_runs",
    "walk_forward_state_cache",
    "hsmm_lifecycle_ui_daily",
]:
    try:
        n = con.execute(f"select count(*) from {table}").fetchone()[0]
        print(f"{table}: {n}")
    except Exception as exc:
        print(f"{table}: missing_or_unreadable: {exc}")
PY
```

The task may still proceed if some optional tables are missing, but the report must say exactly which tables are unavailable.

## Required PR body field

Every PR that depends on the local DB must include:

```text
Local DB validation:
- db path used: ...
- db found: yes/no
- opened read-only: yes/no
- key tables checked: ...
- row counts: ...
- external data fetch: no
- DuckDB committed: no
```

## Failure behavior

If no local DB is available:

- keep the PR as draft;
- mark report status as `partial_missing_db` or `local_db_missing`;
- do not claim data-backed validation passed;
- do not fetch new data to compensate;
- do not create a new empty DB and present it as V0.

## Standard command pattern

Use explicit `--db` where possible:

```bash
python -m src.evaluation.<module> \
  --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" \
  --no-fetch \
  ...
```

## Notes for future work packages

All future work packages that need V0 data must reference this file and include the preflight check before report generation.
