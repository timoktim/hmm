# GPT_EXCHANGE_WP0_hmm_info_exchange_bundle

Project area: GPT analysis integration / information exchange

Work package: WP0

Index id: `GPT-EXCHANGE-WP0-v1`

Primary repo: `timoktim/hmm`

Exchange repo: `timoktim/hmm-info-exchange`

Suggested branch: `gpt-exchange/wp0-hmm-info-exchange-bundle`

Codex instruction: `docs/codex_instructions/gpt_exchange/CODEX_GPT_EXCHANGE_WP0_hmm_info_exchange_bundle.md`

Date: 2026-06-12

## Objective

Add a safe, deterministic information-exchange pipeline that exports current model-derived signal evidence from `hmm` into a separate private GitHub repository named `hmm-info-exchange`, so GPT Pro can read a compact, structured, provenance-aware bundle for explanation and external-search-assisted analysis.

This package must not call the OpenAI API. It must not ask GPT to analyze anything automatically. It only creates the local/export layer that prepares and optionally syncs sanitized model-signal bundles.

## Design principle

Do not let GPT Pro read the full DuckDB database, full score matrices, full target matrices, or private local paths.

Use this architecture:

```text
hmm local model system
→ signal panel snapshot adapter
→ GPT exchange bundle exporter
→ private hmm-info-exchange repository
→ GPT Pro reads/upload/connects exchange bundle
→ user makes final judgment
```

## Preconditions

Required in `hmm`:

```text
src/signals/signal_panel_snapshot.py exists
reports/stage03v/phase2_signal_panel_contract.json status = pass
reports/stage03v/stage03v1_phase1_closeout_report.json status = pass
reports/stage03v/stage03v1_phase2_handoff.json status = pass
```

Required outside this repo:

```text
Private GitHub repository timoktim/hmm-info-exchange exists before sync/push is attempted.
```

If the exchange repo does not exist or is not accessible, the exporter must still support local bundle generation and must return/report:

```text
exchange_repo_status: unavailable_or_not_configured
sync_status: skipped_exchange_repo_unavailable
```

Do not fail local export solely because the exchange repo is missing.

## Scope

Allowed:

- Add a GPT exchange policy config.
- Add a deterministic bundle exporter that reads the existing signal-panel snapshot and Stage03V closeout artifacts.
- Add local output under gitignored `reports/gpt_exchange/latest/` and optional archive output under gitignored `reports/gpt_exchange/archive/`.
- Add optional export-to-repository behavior when `HMM_INFO_EXCHANGE_DIR` points to a local clone of `timoktim/hmm-info-exchange`.
- Add optional git commit/push behavior only behind explicit CLI flags.
- Add repository bootstrap files for `hmm-info-exchange` if the exchange workspace is empty.
- Add tests for schema, privacy/redaction, no-trading-output guardrails, and missing exchange repo behavior.
- Add runtime docs and a GPT Pro prompt template.

Forbidden:

- Do not call the OpenAI API.
- Do not upload anything to external services automatically.
- Do not store GitHub tokens or credentials.
- Do not read or export full DuckDB database files.
- Do not export full target matrices, full feature matrices, raw score matrices, calibrated score matrices, exposure matrices, or event matrices.
- Do not export prospective holdout performance.
- Do not train, refit, recalibrate, or alter model readiness.
- Do not implement Stage03V2 or Stage03V3.
- Do not create buy/sell/position-sizing/recommendation/execution/portfolio-action outputs.
- Do not put raw local absolute paths into the exchange bundle.
- Do not cite invalidated pre-RERUN1 WP4-WP6 or old WP7-v1 artifacts as evidence.

## Required deliverables in `hmm`

Create:

```text
configs/gpt_info_exchange_policy_v1.yaml
src/integrations/gpt_info_exchange.py
scripts/export_gpt_info_exchange_bundle.sh
tests/test_gpt_info_exchange.py
docs/runtime/GPT_INFO_EXCHANGE.md
docs/runtime/GPT_PRO_SIGNAL_ANALYSIS_PROMPT.md
reports/gpt_exchange/README.md
reports/gpt_exchange/sample_manifest.json
```

Update:

```text
.gitignore
docs/work_packages/gpt_exchange/GPT_EXCHANGE_EXECUTION_INDEX.md
```

Optional only if needed:

```text
src/integrations/__init__.py
```

## Exchange repository target structure

The exchange repo `timoktim/hmm-info-exchange` should have this target structure:

```text
README.md
latest/signal_bundle.md
latest/signal_bundle.json
latest/signal_snapshot_lite.csv
latest/watchlists/high_baseline_risk.csv
latest/watchlists/model_baseline_conflicts.csv
latest/watchlists/hsmm_lifecycle_watch.csv
latest/watchlists/stage03v_readiness_watch.csv
latest/provenance.json
latest/prompt_template.md
latest/exchange_manifest.json
archive/YYYYMMDD_HHMMSS/signal_bundle.md
archive/YYYYMMDD_HHMMSS/signal_bundle.json
archive/YYYYMMDD_HHMMSS/signal_snapshot_lite.csv
archive/YYYYMMDD_HHMMSS/watchlists/*.csv
archive/YYYYMMDD_HHMMSS/provenance.json
archive/YYYYMMDD_HHMMSS/exchange_manifest.json
```

The exporter should be able to write these files to a local exchange workspace directory. Git commit/push must be optional and explicit.

## Exchange policy config

Create `configs/gpt_info_exchange_policy_v1.yaml`. It may be JSON-compatible YAML if project conventions prefer that.

Minimum fields:

```text
index_id: GPT-EXCHANGE-WP0-v1
exchange_repo_full_name: timoktim/hmm-info-exchange
exchange_repo_visibility_required: private
local_output_dir: reports/gpt_exchange/latest
local_archive_dir: reports/gpt_exchange/archive
exchange_latest_dir: latest
exchange_archive_dir: archive
max_snapshot_rows: 200
max_watchlist_rows: 50
include_sector_codes: true
include_sector_names: true
include_raw_prices: false
include_raw_ohlcv: false
include_full_matrices: false
include_holdout_performance: false
include_private_paths: false
not_trading_output: yes
bundle_version: gpt_info_exchange_v1
allowed_output_files:
  - signal_bundle.md
  - signal_bundle.json
  - signal_snapshot_lite.csv
  - watchlists/high_baseline_risk.csv
  - watchlists/model_baseline_conflicts.csv
  - watchlists/hsmm_lifecycle_watch.csv
  - watchlists/stage03v_readiness_watch.csv
  - provenance.json
  - prompt_template.md
  - exchange_manifest.json
forbidden_terms:
  - /Users/
  - /private/tmp
  - data/db/
  - .duckdb
  - buy_signal
  - sell_signal
  - position_size
  - position_sizing
  - trade_instruction
  - portfolio_action
  - execution_order
```

## Exporter behavior

Create CLI:

```bash
python -m src.integrations.gpt_info_exchange \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --policy configs/gpt_info_exchange_policy_v1.yaml \
  --output-dir reports/gpt_exchange/latest \
  --archive-dir reports/gpt_exchange/archive \
  --max-rows 200 \
  --max-watchlist-rows 50 \
  --no-push
```

Optional exchange workspace:

```bash
HMM_INFO_EXCHANGE_DIR=../hmm-info-exchange \
python -m src.integrations.gpt_info_exchange \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --exchange-dir "$HMM_INFO_EXCHANGE_DIR" \
  --bootstrap-exchange-repo \
  --write-exchange \
  --no-push
```

Optional explicit push:

```bash
HMM_INFO_EXCHANGE_DIR=../hmm-info-exchange \
python -m src.integrations.gpt_info_exchange \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --exchange-dir "$HMM_INFO_EXCHANGE_DIR" \
  --write-exchange \
  --commit \
  --push
```

Push requirements:

- `--push` must require `--commit`.
- `--commit` must require `--write-exchange`.
- The exporter must never ask for or store tokens.
- If git is unavailable or the directory is not a git repo, return a clear sync skipped/fail status without corrupting local output.

## Bundle content requirements

### `signal_bundle.md`

Must include:

```text
Title and generated_at
not_trading_output warning
signal_date and data freshness summary
baseline-first risk summary
high baseline risk sectors
model-baseline conflict sectors
HSMM lifecycle watch
Stage03V readiness/probability-source summary
external-search prompts / questions for GPT Pro
provenance block
invalidated-artifact warning
manual-review checklist
```

Required warning text:

```text
This bundle is a research/reference artifact for human review. It is not a trading, sizing, buy/sell, recommendation, execution, or portfolio-action instruction.
```

### `signal_bundle.json`

Must include:

```text
index_id
bundle_version
generated_at
signal_date
source_repo
exchange_repo
not_trading_output
summary
watchlists
provenance
policy
boundary_flags
```

### `signal_snapshot_lite.csv`

A capped, light snapshot with no raw OHLCV and no full matrices.

Allowed columns only:

```text
signal_date
sector_id
sector_name
sector_type
data_freshness_status
volatility_band
volatility_percentile_cs
downside_vol_share_20d
downside_vol_share_60d
negative_return_day_share_20d
hmm_state_label
hmm_confidence
prob_trend_up
prob_neutral
prob_risk_off
hsmm_state_phase
hsmm_state_age_days
hsmm_age_bucket
hsmm_duration_percentile
exit_tendency_5d
exit_tendency_10d
exit_tendency_20d
stage03v_readiness_summary
stage03v_probability_display_status
stage03v_probability_source_status
stage03v_risk_ordinal
model_baseline_alignment_status
human_review_note
not_trading_output
```

If a source column is unavailable, keep the column and fill with an explicit unavailable marker.

### Watchlists

Generate capped watchlists:

```text
high_baseline_risk.csv
model_baseline_conflicts.csv
hsmm_lifecycle_watch.csv
stage03v_readiness_watch.csv
```

Suggested rules:

```text
high_baseline_risk: volatility_band in high/extreme or top volatility percentile
model_baseline_conflicts: model_baseline_alignment_status in baseline_high_model_low/baseline_low_model_high
hsmm_lifecycle_watch: hsmm_state_phase late or high exit_tendency_10d/20d when available
stage03v_readiness_watch: rows with usable_probability_candidate summary or probability source available/unavailable notes
```

Do not fabricate calibrated probabilities if the current per-entity score source is unavailable.

### `prompt_template.md`

Create a GPT Pro prompt template that instructs GPT to:

```text
read the bundle and watchlists
separate model evidence, external public information, and inference
use web/search to check recent public explanations for highlighted sectors
state uncertainty
not output buy/sell/position/execution advice
produce manual-review questions
```

## Provenance requirements

Create `provenance.json` with:

```text
source_repo: timoktim/hmm
exchange_repo: timoktim/hmm-info-exchange
signal_panel_contract_path
stage03v_closeout_report_path
stage03v_phase2_handoff_path
stage03v_final_gate_v2_path
stage03v_invalidated_artifact_registry_path
signal_snapshot_source
export_policy_path
not_trading_output: yes
invalidated_artifact_policy: old WP4-WP6 and old WP7-v1 artifacts are not signal evidence
```

Do not include raw local absolute paths or token/credential data.

## Required local status artifact

Create committed sample only, not live data:

```text
reports/gpt_exchange/sample_manifest.json
```

Live outputs under `reports/gpt_exchange/latest/` and `reports/gpt_exchange/archive/` must be gitignored unless a future package explicitly promotes a small public sample fixture.

## Tests

Create `tests/test_gpt_info_exchange.py` with at least:

- Policy config loads and validates.
- Exporter builds required output file set from a synthetic signal snapshot.
- `signal_snapshot_lite.csv` contains only allowed columns and respects row caps.
- Watchlists respect max row cap.
- Missing exchange repo does not fail local export.
- `--push` without `--commit` is rejected.
- `--commit` without `--write-exchange` is rejected.
- Bundle contains required not-trading-output warning.
- Bundle does not contain forbidden terms or private local paths.
- Bundle does not contain `.duckdb` path or raw DB path.
- No buy/sell/position-sizing/recommendation/execution/portfolio-action fields are created.
- Invalidated artifact warning is present.
- GPT prompt template includes search/external-context instruction and no-trading-output constraint.

## Gate script

Create:

```text
scripts/gpt_info_exchange_gate.sh
```

It must run:

```bash
python -m compileall -q src tests
pytest -q tests/test_gpt_info_exchange.py
python -m src.integrations.gpt_info_exchange --policy configs/gpt_info_exchange_policy_v1.yaml --output-dir reports/gpt_exchange/latest --archive-dir reports/gpt_exchange/archive --synthetic --no-push
python -m json.tool reports/gpt_exchange/latest/signal_bundle.json >/dev/null
python -m json.tool reports/gpt_exchange/latest/provenance.json >/dev/null
python -m json.tool reports/gpt_exchange/latest/exchange_manifest.json >/dev/null
python -m json.tool reports/gpt_exchange/sample_manifest.json >/dev/null
bash scripts/check_no_private_paths.sh
git diff --check
git diff --cached --check
```

Stable marker:

```text
GPT_INFO_EXCHANGE_GATE=<status> output_dir=<path> exchange_repo_status=<status> snapshot_rows=<n> watchlists=<n> not_trading_output=yes push=<yes/no>
```

## Acceptance criteria

WP0 passes if:

- A deterministic local GPT exchange bundle can be generated without access to the exchange repo.
- Optional exchange workspace export is implemented behind explicit flags.
- Optional commit/push is implemented only behind explicit flags and never stores credentials.
- Output is capped, redacted, and contains no raw DB/full matrix/private path artifacts.
- The bundle includes signal summary, watchlists, provenance, invalidated-artifact warning, and GPT Pro prompt template.
- No OpenAI API call occurs.
- No Stage03V artifacts, model semantics, readiness policies, or holdout state are modified.
- Tests and gate pass.

## Return format

```text
index_id: GPT-EXCHANGE-WP0-v1
branch: gpt-exchange/wp0-hmm-info-exchange-bundle
PR: ...
status: pass / partial / fail

commands run:
- ...

files changed:
- ...

exchange repo exists/accessed: yes/no/not_checked
local bundle export: pass/fail
exchange workspace export: pass/skipped/fail
commit implemented: yes/no
push implemented: yes/no
push executed: yes/no
output dir: ...
archive dir: ...
snapshot rows exported: ...
watchlists generated: ...
prompt template path: ...
provenance path: ...
manifest path: ...

OpenAI API called: no
external upload automatic: no
credentials stored: no
raw DuckDB exported: no
full matrices exported: no
holdout consumed: no
Stage03V artifacts modified: no
model training/recalibration: no
trading or decision output: no
private paths leaked: no
invalidated artifacts used as evidence: no

remaining risks:
- ...
```
