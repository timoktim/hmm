# Database Workspace Manager

Stage04-DATA-WP3A adds a local DuckDB workspace manager for the Streamlit app. It lets operators see which database is active, create a new empty Tushare-profile database, switch to an existing database, copy an archive, and run schema/data sanity checks before later rebuild work.

## What It Solves

Before WP3A, `app.py` always opened `settings.db_path` through `DuckDBStorage()`. That made the active database implicit and made it easy to confuse the original local DB with a newly prepared Tushare DB. The workspace manager makes the active DB visible in the sidebar and keeps the selected path in `data/db/workspace_config.json`.

Active path resolution order:

1. Streamlit session state `active_db_path`
2. `data/db/workspace_config.json`
3. `settings.db_path`, including the `ASHARE_HMM_DB_PATH` environment override

`workspace_config.json` is local runtime state and is ignored by Git. It stores only a project-relative DB path and update metadata. It never stores Tushare tokens or other credentials.

## Supported Operations

New database:

- Creates a `.duckdb` file under `data/db/`.
- Refuses to overwrite an existing file.
- Uses the `tushare_empty` profile.
- Initializes the repo schema by default.
- Writes `database_workspace_metadata` with profile, creator, created time, schema version placeholder, and active source.

Open existing database:

- Lists `.duckdb` files under `data/db/`.
- Requires the selected file to exist.
- Requires the `.duckdb` suffix.
- Runs a read-only schema check before switching.
- Allows incomplete schema to be reported clearly instead of silently creating a new database.

Archive current database:

- Creates a copy under `data/db/archive/`.
- Leaves the source database in place.
- Leaves the active DB unchanged.

Validate current database:

- Checks file existence, suffix, read-only connect, and core tables.
- Reports key row counts, latest trade dates, `stock_ohlcv` source distribution, duplicate `stock_code + trade_date`, current `data_health` failures, and latest QFQ rebuild audit run.
- Does not modify the DB unless the UI operator explicitly enables the schema initialization idempotency check.

## Safety Boundary

WP3A intentionally does not provide any destructive database operation. It avoids broad cleanup actions because Stage04 is still separating the original local DB, Tushare primary data, QFQ rebase state, model artifacts, and future clean-snapshot rebuilds. A mistaken destructive operation here could invalidate existing HMM/HSMM/Hazard artifacts without producing a complete replacement.

WP3A also does not run:

- Full Tushare historical fetches
- Clean Tushare snapshot rebuilds
- QFQ affected-stock rebuild execution
- HMM, HSMM, or Hazard retraining
- Final holdout reads

## WP3B Boundary

The clean Tushare-only DB snapshot pipeline belongs to Stage04-DATA-WP3B. WP3B should create and populate a fresh database with Tushare stock basics, trade calendar, daily OHLCV, adj factors, daily basics, indices, derived sector data, market breadth, and feature caches. WP3A only prepares the workspace manager needed to do that safely.

## Legacy DB And Model Artifacts

Switching the active DB changes what the UI reads and writes after rerun. Existing model files under `data/models/` are not moved or rewritten by WP3A. When a new clean DB is prepared in WP3B, model artifacts that were trained from an older DB should be treated as stale until retrained or explicitly validated against the new data snapshot.

## Environment Fallback

If no workspace config is present, the default database still comes from `settings.db_path`. Since settings use the `ASHARE_HMM_` prefix, operators can set:

```bash
export ASHARE_HMM_DB_PATH=data/db/a_share_hmm.duckdb
```

This fallback is only used when the Streamlit session state and `workspace_config.json` do not specify an active DB.
