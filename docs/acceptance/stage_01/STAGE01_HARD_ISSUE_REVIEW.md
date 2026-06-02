# Stage 01 Hard Issue Review

Index ID: STAGE01-WP-D-v1
Branch: stage01/wp-d-integration-summary
Verdict: Stage01PassWithTrackedRisks

## Checklist

### Repository and Package Boundary

- Stage 01 does not modify HMM/HSMM training algorithms: pass. The Stage 01 diff from `23aecc7` through current `main` has no changes under `src/models/`.
- Stage 01 does not modify feature generation logic: pass. The Stage 01 diff has no changes under `src/features/`.
- Stage 01 does not add Robust HMM, Sticky HMM, Student-t emissions, BOCPD, duration hazard, or decision engine: pass. No such implementation was added by WP-A/WP-B/WP-C.
- Stage 01 does not fetch external market or constituent data: pass. All diagnostic reruns used `--no-fetch`, and report payloads record external data fetch as `false` or `no`.
- DuckDB/WAL files are not committed: pass. `git ls-files data/db` and `git ls-files '*.duckdb' '*.wal'` returned no tracked files.
- Reports are committed only under work-package report directories: pass. Stage 01 diagnostic reports remain under `reports/hmm_confidence/`, `reports/hmm_label_alignment/`, `reports/hmm_churn_dwell/`, and this review adds `reports/stage01_integration/`.

### Data-Backed Diagnostics

- WP-A confidence report status is `pass`: pass.
- WP-A uses posterior columns as state confidence only: pass. The report explicitly states posterior probabilities are not return, rising, falling, profit, buy, or sell probabilities.
- WP-B label alignment report status is `pass`: pass.
- WP-B reports label preservation, ambiguity, drift, and state identity readiness: pass.
- WP-C churn/dwell report status is `pass`: pass.
- WP-C reports confidence integration as available: pass (`available_confidence`).
- WP-C reports alignment integration as available: pass (`available_alignment`).
- WP-C reports causal cache status explicitly: pass (`causal_cache_available: false`).
- Reports use one run id or clearly explain differences: pass. WP-A, WP-B, and WP-C all resolve to `bea7ff20106a`.
- Confidence/alignment/churn are mutually readable: pass. WP-C reads WP-A and WP-B DB outputs from the same local DB.

### Interpretation and Readiness

- HMM confidence remains an internal diagnostic/state confidence measure: pass.
- HMM confidence is not presented as return probability or buy/sell probability: pass.
- Label alignment ambiguity is tracked as a conservative-readiness risk: pass.
- Churn/dwell metrics are diagnostic and not decision-ready: pass.
- Causal cache unavailable keeps readiness at `research_only`: pass.
- No report incorrectly upgrades Stage 01 to `validated` or `decision_ready`: pass. WP-A is `internal_only`; WP-B and WP-C remain `research_only`.

## Blocking Issues

None.

## Non-Blocking But Must Track

- No GitHub Actions CI. There is no `.github/workflows` directory in the repository.
- Causal cache metadata is unavailable, so WP-C readiness remains `research_only`.
- Label alignment ambiguity remains high at `0.8666666666666667`.
- Validation relies on a local V0 DuckDB and local command logs rather than a CI-managed DB artifact.

## Informational

- The local DB was reached through the canonical ignored path `data/db/a_share_hmm.duckdb`, symlinked to the existing V0 DB.
- Read-only DB preflight succeeded before report generation.
- The diagnostic reruns update local DB output tables, but the DB and WAL remain ignored and untracked.

## Recommendations For Stage 02

- Add CI coverage for report generation that can run without private DB data, plus an explicit path for DB-backed validation artifacts.
- Add or formalize causal walk-forward cache metadata if stronger readiness is expected.
- Treat high alignment ambiguity as a state identity risk until additional stability evidence is available.
- Keep posterior probability wording restricted to state confidence unless a later validated probability work package changes the policy.
