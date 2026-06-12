# CODEX_GPT_EXCHANGE_WP0_hmm_info_exchange_bundle

Repository: `timoktim/hmm`

Index id: `GPT-EXCHANGE-WP0-v1`

Work package: `docs/work_packages/gpt_exchange/GPT_EXCHANGE_WP0_hmm_info_exchange_bundle.md`

Exchange repo: `timoktim/hmm-info-exchange`

Suggested branch: `gpt-exchange/wp0-hmm-info-exchange-bundle`

## Instruction

Start from updated `main`. Execute only this work package:

```text
docs/work_packages/gpt_exchange/GPT_EXCHANGE_WP0_hmm_info_exchange_bundle.md
```

## Required outcome

Implement a safe GPT Pro information-exchange export pipeline:

```text
hmm local signal snapshot
→ capped/redacted GPT exchange bundle
→ optional local clone of timoktim/hmm-info-exchange
→ optional explicit commit/push
```

The first version must not call the OpenAI API and must not automatically upload anything to external services.

## Exchange repo handling

The desired exchange repository is:

```text
timoktim/hmm-info-exchange
```

If it does not exist or is not accessible from the environment, do not fail local bundle export. Report:

```text
exchange_repo_status: unavailable_or_not_configured
sync_status: skipped_exchange_repo_unavailable
```

If a local exchange clone is provided through `HMM_INFO_EXCHANGE_DIR` or `--exchange-dir`, the exporter may write exchange files there. Git commit/push must be explicit:

```text
--write-exchange
--commit
--push
```

`--push` requires `--commit`; `--commit` requires `--write-exchange`.

Do not store credentials or tokens.

## Boundary reminders

Do not:

```text
call OpenAI API
upload externally by default
store GitHub tokens or credentials
export raw DuckDB or full matrices
export raw OHLCV/full target/full feature/raw score/calibrated score/exposure/event matrices
consume prospective holdout
train/refit/recalibrate models
modify Stage03V artifacts or readiness policies
create buy/sell/position-sizing/recommendation/execution/portfolio-action outputs
leak raw local absolute paths
use invalidated pre-RERUN1 WP4-WP6 or old WP7-v1 artifacts as signal evidence
```

Use the return format specified in the work package when opening the PR.
