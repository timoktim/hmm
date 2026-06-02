# Local DB Artifact Policy

Index ID: STAGE02-WP-B-v1

## Rule

The V0 DuckDB and any WAL file are runtime artifacts and must never be committed. Local DB-backed validation is allowed only as a local evidence path, separate from CI-safe validation.

## Allowed path records

Committed docs and reports may record:

- canonical repo-relative path: `data/db/a_share_hmm.duckdb`
- environment override name: `ASHARE_HMM_DB_PATH`
- redacted value: `<redacted-local-db-path>`
- generic placeholder: `/absolute/path/to/a_share_hmm.duckdb`

Committed docs and reports must not record full private absolute paths, machine-specific worktree paths, or absolute paths ending in a DuckDB/WAL filename.

## Required local DB report fields

Every local DB-backed validation report or PR body must include:

- local DB available: yes/no
- db path used: canonical repo-relative or redacted path
- opened read-only when applicable: yes/no
- key tables checked when applicable
- external data fetch: no
- training algorithm modified: no
- DuckDB committed: no

## CI relationship

CI must stay private-DB-free. If the private DB is missing in CI, that is expected and must not be reported as a validation failure for the CI-safe skeleton. Data-backed report generation belongs to local validation, not the default GitHub Actions path.
