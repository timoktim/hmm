# STAGE03PF_BATCH_03_READINESS_UI_UNIVERSE_EVIDENCE

Purpose: harden readiness, UI/analysis selection, universe/data lineage, evidence registry, and lower-priority SQL/text hygiene before Stage03 model work.

This batch contains:

- WP8 Probability Readiness Lineage, P1
- WP9 UI and Analysis Selection Gate, P1
- WP10 Universe/Data Snapshot Lineage, P1
- WP11 Evidence Registry Minimal Contract, P1
- WP12 SQL Identifier Hardening and Legacy Probability Wording, P2/P3

WP8 and WP10 can run after WP1/WP6. WP9 depends on WP1/WP6/WP8. WP11 depends on WP8/WP9. WP12 can be deferred until after WP9, and does not block Stage03 if explicitly accepted as deferred.

Do not implement Duration Hazard, BOCPD, Decision Engine, or new model training in this batch.

## Shared rules

- One PR per WP.
- Start from updated `main`.
- Do not fetch external data.
- Do not commit DuckDB/WAL files.
- Read `docs/runtime/LOCAL_DB_HANDOFF.md` before DB-backed validation.
- Lineage/readiness mismatch must fail closed.
- Raw/calibrated `p_exit` must not bypass readiness gate.
- UI must not present probability outputs as trading advice.

---

## WP8 Probability Readiness Lineage

Level: P1, recommended Stage03 blocker

Goal: bind probability readiness reports to run/config/lineage so a readiness matrix from one run cannot be applied to another.

Allowed files:

```text
src/evaluation/hsmm_lifecycle_probability_report.py
src/evaluation/hsmm_display_lifecycle.py
src/evaluation/hsmm_exit_calibration.py
tests/test_probability_readiness_lineage.py
tests/test_probability_gate_strictness.py
```

Codex tasks:

1. Add required fields to readiness matrix:

```text
run_id
config_hash
lineage_hash
profile_mode
profile_cutoff_date
state_date_policy
feature_scope_id
exit_type
horizon_days
probability_status
created_at
```

2. `_read_probability_status()` must accept expected metadata and validate all required fields.
3. Missing field or mismatch must return missing/invalid; raw score cannot be used.
4. Tighten raw rank policy:

```text
usable_probability: numeric and calibrated probability allowed
raw_only: internal diagnostic rank only, no probability-like UI field
ordinal_only: no raw p_exit rank, use age/empirical baseline or unavailable
invalid/insufficient_sample/missing: no raw score
```

5. Add lifecycle daily fields:

```text
exit_tendency_*_readiness_status
exit_tendency_*_raw_score_used
exit_tendency_*_raw_basis
```

Tests required:

- Readiness matrix run_id mismatch disables raw score.
- config_hash mismatch disables raw score.
- lineage_hash mismatch disables raw score.
- ordinal_only disables raw score.
- invalid/missing/insufficient_sample disables raw score.
- raw/calibrated `p_exit` does not appear in lifecycle UI output.

Required validation:

```bash
python -m compileall -q src tests
pytest -q tests/test_probability_readiness_lineage.py tests/test_probability_gate_strictness.py tests/test_lifecycle_*.py
```

PR return format:

```text
WP: STAGE03PF-WP8
status: pass / partial / fail
branch: stage03pf/wp8-probability-readiness-lineage
PR: ...
commands run:
- ...
readiness matrix:
- run/config/lineage checked: yes/no
- ordinal_only raw score blocked: yes/no
- raw/calibrated p_exit UI blocked: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## WP9 UI and Analysis Selection Gate

Level: P1, recommended Stage03 blocker

Goal: ensure UI/analysis defaults only select completed, readiness-valid, lineage-matched runs/caches.

Dependency: WP1, WP6, WP8.

Allowed files:

```text
src/ui/lifecycle_page.py
src/ui/components/model_workflow.py
src/ui/state_screener_page.py
src/analysis/sector_cycles.py
src/ui/run_context.py
tests/test_ui_readiness_selection.py
tests/test_analysis_cache_selection.py
```

Codex tasks:

1. Add selector helpers, for example:

```text
storage.list_valid_walk_forward_caches(scope, require_completed=True, require_lineage=True)
storage.latest_completed_hsmm_lifecycle_run(...)
```

2. Lifecycle page selector must require:

```text
hsmm_model_runs.run_status = completed
lifecycle profile metadata exists
readiness/evidence status is not invalid
```

3. Model workflow cache selector must require:

```text
cache_status = completed
lineage_hash IS NOT NULL
row_count > 0
causal audit acceptable
universe/scope match
```

4. State screener cache options must show status; default list only valid caches; legacy caches only in debug/legacy UI.
5. `load_sector_states_for_analysis()` must validate metadata before reading cache. On mismatch, return empty or raise a clear error.

Tests required:

- Latest selector ignores running/failed HSMM run.
- Latest selector ignores run with missing lifecycle profile.
- Cache selector ignores legacy cache.
- Cache selector ignores universe mismatch cache.
- Analysis loader rejects lineage mismatch cache.

Required validation:

```bash
python -m compileall -q src tests
pytest -q tests/test_ui_readiness_selection.py tests/test_analysis_cache_selection.py
```

PR return format:

```text
WP: STAGE03PF-WP9
status: pass / partial / fail
branch: stage03pf/wp9-ui-analysis-selection-gate
PR: ...
commands run:
- ...
selectors:
- completed run only: yes/no
- lineage matched cache only: yes/no
- legacy cache hidden by default: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## WP10 Universe/Data Snapshot Lineage

Level: P1, recommended Stage03 blocker

Goal: include universe membership, custom basket membership, source data snapshot, and calendar digest in lineage so data revisions invalidate caches.

Dependency: WP1.

Allowed files:

```text
src/data_pipeline/universe.py
src/features/custom_basket_features.py
src/data_pipeline/storage.py
src/backtest/sector_rotation.py
tests/test_universe_data_lineage.py
```

Codex tasks:

1. Add digest helpers:

```text
compute_universe_membership_hash(storage, universe_id, as_of_date=None)
compute_custom_basket_membership_hash(storage, include_ids=None, as_of_date=None)
compute_sector_ohlcv_snapshot_hash(storage, sector_ids, start_date, end_date)
compute_calendar_hash(trade_dates)
```

2. Add these digests to lineage payloads.
3. For custom baskets, if no historical membership schema exists, use current membership digest and mark `membership_policy='current_snapshot'`.
4. Reserve `valid_from` / `valid_to` fields for future SCD support, but do not implement a broad SCD migration here.
5. HMM cache key and HSMM run lineage must include relevant digests.

Tests required:

- Universe membership change changes hash.
- Custom basket weight/member change changes hash.
- One OHLCV close value change changes data snapshot hash.
- trade_dates change changes calendar hash.
- cache params include these digests.

Required validation:

```bash
python -m compileall -q src tests
pytest -q tests/test_universe_data_lineage.py tests/test_hmm_walk_forward_cache_contract.py
```

PR return format:

```text
WP: STAGE03PF-WP10
status: pass / partial / fail
branch: stage03pf/wp10-universe-data-snapshot-lineage
PR: ...
commands run:
- ...
digests:
- universe: yes/no
- custom basket: yes/no
- data snapshot: yes/no
- calendar: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## WP11 Evidence Registry Minimal Contract

Level: P1, recommended Stage03 blocker

Goal: create a minimal evidence registry that Stage03 can use as the single artifact selection entry point.

Dependency: WP8, WP9.

Allowed files:

```text
src/data_pipeline/storage.py
src/evaluation/evidence_registry.py
src/ui/lifecycle_page.py
src/ui/components/model_workflow.py
tests/test_evidence_registry_contract.py
```

Codex tasks:

1. Create or extend `model_evidence_registry` with:

```text
evidence_id
run_id
artifact_type
artifact_path
lineage_hash
feature_scope_id
universe_id
profile_mode
profile_cutoff_date
state_date_policy
evidence_level
readiness_status
verdict
created_at
metadata_json
```

2. Ensure evidence levels are defined:

```text
exploratory
internal_diagnostic
validated_signal
decision_support
```

3. Lifecycle UI rows or profile metadata must be able to link to an evidence entry.
4. UI may display evidence_level, but not as trading advice.
5. Stage03 future input selectors must use only registry artifacts with acceptable readiness and matching lineage.
6. Missing evidence means legacy/debug, not valid default input.

Tests required:

- Insert evidence and query by run_id / lineage_hash.
- UI selector can retrieve evidence_level.
- Invalid readiness artifact is not returned by default selector.
- Missing evidence artifact is marked legacy/debug.

Required validation:

```bash
python -m compileall -q src tests
pytest -q tests/test_evidence_registry_contract.py tests/test_ui_readiness_selection.py
```

PR return format:

```text
WP: STAGE03PF-WP11
status: pass / partial / fail
branch: stage03pf/wp11-evidence-registry-minimal-contract
PR: ...
commands run:
- ...
evidence registry:
- query by run_id: yes/no
- query by lineage_hash: yes/no
- invalid readiness hidden: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## WP12 SQL Identifier Hardening and Legacy Probability Wording

Level: P2/P3, optional before Stage03 but recommended before broader UI exposure

Goal: reduce maintenance/security risk and remove misleading probability wording.

Dependency: WP9 recommended.

Allowed files:

```text
src/data_pipeline/storage.py
src/ui/sector_detail.py
src/ui/help_texts.py
tests/test_storage_identifier_quoting.py
tests/test_ui_text_policy.py
```

Codex tasks:

1. Harden `upsert_df()` table/column identifiers with whitelist or safe quote helper.
2. Do not let arbitrary external table/column strings enter f-string SQL.
3. Change UI wording:

```text
趋势上行概率 -> TrendUp 状态后验 / 趋势状态后验
下一状态概率 -> 状态转移后验 / 模型迁移分布
```

4. Keep clear help text: these are not rising/falling/return/buy/sell probabilities.
5. Clean legacy `RiskOff` display wording where safe. Keep internal enum compatibility separate from display labels.

Tests required:

- Illegal table name rejected.
- Illegal column name rejected.
- Legal upsert still works.
- UI forbidden term count does not increase.

Required validation:

```bash
python -m compileall -q src tests
pytest -q tests/test_storage_identifier_quoting.py tests/test_ui_text_policy.py
```

PR return format:

```text
WP: STAGE03PF-WP12
status: pass / partial / fail
branch: stage03pf/wp12-sql-ui-text-hygiene
PR: ...
commands run:
- ...
hardening:
- unsafe identifiers rejected: yes/no
- UI forbidden terms not increased: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```