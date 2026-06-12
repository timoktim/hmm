# GPT Info Exchange

`GPT-EXCHANGE-WP0-v1` adds a local, redacted information-exchange exporter for human GPT Pro review.

The exporter reads the signal-panel snapshot adapter and Stage03V provenance artifacts, writes a capped bundle under `reports/gpt_exchange/latest/`, and optionally copies that bundle into a local clone of `timoktim/hmm-info-exchange`.

It does not call the OpenAI API and does not automatically upload anything.

## Local Bundle

```bash
bash scripts/export_gpt_info_exchange_bundle.sh \
  --policy configs/gpt_info_exchange_policy_v1.yaml \
  --output-dir reports/gpt_exchange/latest \
  --archive-dir reports/gpt_exchange/archive \
  --synthetic \
  --no-push
```

For a local read-only DB-backed snapshot, pass `--db` to the script. The DB path is used only for local reads and is not written into the bundle.

## Exchange Workspace

Writing to the exchange repository is explicit:

```bash
HMM_INFO_EXCHANGE_DIR=../hmm-info-exchange \
bash scripts/export_gpt_info_exchange_bundle.sh \
  --exchange-dir "$HMM_INFO_EXCHANGE_DIR" \
  --bootstrap-exchange-repo \
  --write-exchange \
  --no-push
```

Commit and push are separate explicit steps:

```bash
HMM_INFO_EXCHANGE_DIR=../hmm-info-exchange \
bash scripts/export_gpt_info_exchange_bundle.sh \
  --exchange-dir "$HMM_INFO_EXCHANGE_DIR" \
  --write-exchange \
  --commit \
  --push
```

`--commit` requires `--write-exchange`, and `--push` requires `--commit`.

## Outputs

- `signal_bundle.md`
- `signal_bundle.json`
- `signal_snapshot_lite.csv`
- `watchlists/high_baseline_risk.csv`
- `watchlists/model_baseline_conflicts.csv`
- `watchlists/hsmm_lifecycle_watch.csv`
- `watchlists/stage03v_readiness_watch.csv`
- `provenance.json`
- `prompt_template.md`
- `exchange_manifest.json`

Live outputs under `reports/gpt_exchange/latest/` and `reports/gpt_exchange/archive/` are gitignored. Only `reports/gpt_exchange/README.md` and `reports/gpt_exchange/sample_manifest.json` are committed in WP0.

## Guardrails

The bundle is a research/reference artifact for human review. It is not a trading, sizing, buy/sell, recommendation, execution, or portfolio-action instruction.

The exporter does not export raw DuckDB files, raw OHLCV rows, full target matrices, full feature matrices, score matrices, exposure matrices, event matrices, prospective holdout performance, credentials, or local absolute paths.

Invalidated pre-RERUN1 WP4-WP6 and old WP7-v1 artifacts are preserved as warnings and are not used as signal evidence.

## Gate

```bash
bash scripts/gpt_info_exchange_gate.sh
```

The gate runs compile checks, unit tests, synthetic bundle export, JSON validation, private-path hygiene, and diff checks.
