# STAGE03PF_BATCH_01_HMM_CACHE_LINEAGE

Purpose: make HMM walk-forward cache identity, read/write behavior, and feature-state merge behavior lineage-safe.

This batch contains two sequential packages:

- WP2 HMM Walk-forward Cache Contract
- WP3 Cached State / Feature Merge Guard

Do not implement Stage03 models. Do not change HMM training algorithm except for cache metadata/read-write contract integration.

## Dependency and branch order

WP2 depends on WP1 Lineage Core. WP3 depends on WP1 and WP2.

Suggested branches:

```text
stage03pf/wp2-hmm-walk-forward-cache-contract
stage03pf/wp3-cached-state-feature-guard
```

## Shared rules

- Start from updated `main` after WP1 is merged.
- One PR per WP.
- Do not fetch external data.
- Do not commit DuckDB/WAL files.
- Legacy cache with missing `lineage_hash` must not be a valid default cache.
- Lineage mismatch must fail closed.

---

## WP2 HMM Walk-forward Cache Contract

Level: P0

Goal: fix incomplete HMM walk-forward cache key and unsafe cache reads.

Allowed files:

```text
src/backtest/sector_rotation.py
src/models/walk_forward.py
src/models/hmm_model.py
src/data_pipeline/storage.py
tests/test_lineage_hash_contract.py
tests/test_hmm_walk_forward_cache_contract.py
```

Codex tasks:

1. Derive `cache_key` from `lineage_hash`, or include `lineage_hash` in the key.
2. Expand cache params to include at least:

```text
n_states
train_window_days
retrain_frequency
random_state
n_iter
tol
min_train_rows
min_sequence_length
feature_columns
feature_version
feature_scope_id
include_custom_baskets
universe_id
state_date_mode
rebalance_days
start_date
end_date
data_snapshot_hash
universe_membership_hash
calendar_hash
```

3. Update cache read contract:

```text
_read_walk_forward_cache(storage, cache_key, expected_lineage_hash)
```

must reject or return empty when:

```text
run metadata missing
cache_status != completed
lineage_hash mismatch
row_count != actual state rows
max_observation_date_used > trade_date
legacy lineage_hash is null
```

4. Update write contract:

```text
_write_walk_forward_cache()
```

must write state rows first, then completed metadata with:

```text
cache_status=completed
completed_at
lineage_json
lineage_hash
feature_lineage_hash
```

If writing state rows fails, completed cache metadata must not be left behind.

5. UI/debug behavior: legacy cache may be displayed only as legacy/debug, never as default causal cache.

Tests required:

- Changing `n_iter` changes cache key.
- Changing feature columns changes cache key.
- Changing `random_state` changes cache key.
- `cache_status=running` is rejected.
- mismatched `lineage_hash` is rejected.
- `max_observation_date_used > trade_date` is rejected.
- legacy `lineage_hash IS NULL` is rejected.

Required validation:

```bash
python -m compileall -q src tests
pytest -q tests/test_lineage_hash_contract.py tests/test_hmm_walk_forward_cache_contract.py
```

PR return format:

```text
WP: STAGE03PF-WP2
status: pass / partial / fail
branch: stage03pf/wp2-hmm-walk-forward-cache-contract
PR: ...
commands run:
- ...
cache contract:
- lineage_hash in key: yes/no
- running cache rejected: yes/no
- legacy cache rejected by default: yes/no
- causal boundary checked: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## WP3 Cached State / Feature Merge Guard

Level: P0

Goal: prevent old cached states from being silently merged with newly built features.

Allowed files:

```text
src/backtest/sector_rotation.py
src/analysis/sector_cycles.py
src/scoring/sector_ranker.py
tests/test_hmm_cached_state_feature_guard.py
```

Codex tasks:

1. Create or reuse `feature_lineage_hash` on feature frames.
2. Persist `feature_lineage_hash` in cache metadata and required state rows.
3. Before merging features with cached states, validate:

```text
current feature_lineage_hash == cache.feature_lineage_hash
current feature_scope_id == cache.feature_scope_id
current universe_id == cache.universe_id
current date range covers cache state dates
```

4. On validation failure:

```text
invalidate cache and recompute
or raise explicit LineageMismatchError
```

5. Silent merge is forbidden.

Tests required:

- Matching feature/state lineage can merge.
- Changed current features hash rejects merge.
- Universe/scope change rejects merge.
- Legacy cache missing `feature_lineage_hash` is rejected for backtest.

Required validation:

```bash
python -m compileall -q src tests
pytest -q tests/test_hmm_cached_state_feature_guard.py tests/test_hmm_walk_forward_cache_contract.py
```

PR return format:

```text
WP: STAGE03PF-WP3
status: pass / partial / fail
branch: stage03pf/wp3-cached-state-feature-guard
PR: ...
commands run:
- ...
merge guard:
- feature_lineage_hash generated: yes/no
- mismatch rejected: yes/no
- legacy cache rejected: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```