# CODEX_THREAD_A_RECOVER_WP_A

Repository: timoktim/hmm
Assigned index_id: STAGE00-WP-A-v1
Current branch: stage00/wp-a-evidence-registry
Current PR: https://github.com/timoktim/hmm/pull/1

## Situation

The repository was initially missing the V0 baseline source. You synced the local V0 source into `stage00/wp-a-evidence-registry` and implemented WP-A evidence registry. That recovery action is acceptable, but PR #1 now has two scopes:

1. Bootstrap import of V0 baseline source into GitHub.
2. Stage 00 WP-A evidence registry implementation.

Do not continue into WP-B or WP-C. Your job now is to clean up and finalize PR #1.

## Required actions

1. Keep the V0 source at repository root. Do not move `app.py`, `src/`, `tests/`, or `requirements.txt` into a nested directory.
2. Confirm `.gitignore` excludes runtime and large local artifacts:
   - `data/db/*.duckdb`
   - `data/cache/`
   - `data/logs/`
   - `data/models/`
   - `.venv/`
   - `*.zip`
3. Update PR title to:

```text
[bootstrap+wp-a] Import V0 baseline and add Stage 00 evidence registry
```

4. Update PR body to explicitly state:
   - The GitHub repo was empty/missing V0 source.
   - This PR imports the V0 baseline source.
   - This PR implements only `STAGE00-WP-A-v1`.
   - This PR does not implement WP-B or WP-C.
   - WP-B/WP-C should start from updated `main` after this PR is merged, or stack on this branch if needed.
5. Re-run:

```bash
python -m compileall -q src tests
pytest -q tests/test_evidence_registry.py tests/test_validation_runs_registry.py
pytest -q -m "not slow"
```

6. Ensure the report remains available:

```text
reports/evidence_registry/stage00_wp_a_registry_summary.md
reports/evidence_registry/stage00_wp_a_registry_summary.json
```

7. Do not fetch new market data. Do not modify HMM/HSMM training algorithms. Do not modify UI display logic.

## Return format

Return the following:

```text
Thread: A
index_id: STAGE00-WP-A-v1
branch: stage00/wp-a-evidence-registry
PR: https://github.com/timoktim/hmm/pull/1
status: pass / partial / fail
scope clarification complete: yes/no
bootstrap import included: yes
WP-A implementation complete: yes/no
commands run:
- ...
results:
- ...
reports:
- ...
external data fetch: no
training algorithm modified: no
UI display logic modified: no
risks:
- ...
```
