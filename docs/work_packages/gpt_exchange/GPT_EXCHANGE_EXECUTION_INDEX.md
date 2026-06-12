# GPT_EXCHANGE_EXECUTION_INDEX

Status: active
Area: GPT Pro analysis integration / information exchange
Active package: GPT-EXCHANGE-WP0-v1

## Purpose

This index tracks work for exporting HMM/HSMM/Stage03V signal evidence into a separate private information-exchange repository for GPT Pro analysis and explanation.

The exchange repo is intended to be:

```text
timoktim/hmm-info-exchange
```

It should contain capped, redacted, provenance-aware signal bundles only. It must not contain raw DuckDB files, full matrices, private local paths, tokens, or trading/execution instructions.

## Route Anchors

- `src/signals/signal_panel_snapshot.py`
- `docs/runtime/STAGE03V_SIGNAL_PANEL_CONTRACT.md`
- `reports/stage03v/phase2_signal_panel_contract.json`
- `reports/stage03v/stage03v1_phase1_closeout_report.json`
- `reports/stage03v/stage03v1_phase2_handoff.json`
- `reports/stage03v/stage03v1_invalidated_artifact_registry.json`
- `docs/work_packages/gpt_exchange/GPT_EXCHANGE_WP0_hmm_info_exchange_bundle.md`
- `docs/codex_instructions/gpt_exchange/CODEX_GPT_EXCHANGE_WP0_hmm_info_exchange_bundle.md`

## Package Sequence

| index_id | package | status | branch | purpose |
|---|---|---|---|---|
| GPT-EXCHANGE-WP0-v1 | HMM Info Exchange Bundle Exporter | active | gpt-exchange/wp0-hmm-info-exchange-bundle | create deterministic local/export bundle for GPT Pro and optional sync to hmm-info-exchange |
| GPT-EXCHANGE-WP1 | GPT Interpretation Archive and Review Notes | blocked_until_wp0_accepted | TBD | archive GPT-generated interpretations and manual-review questions without feeding them into training |
| GPT-EXCHANGE-WP2 | Optional Read-Only Connector / MCP Layer | blocked_pending_explicit_approval | TBD | optional future connector after bundle workflow proves useful |

## Execution Rules

1. Only GPT-EXCHANGE-WP0-v1 is executable in the current exchange sequence.
2. WP0 must not call OpenAI API.
3. WP0 must not automatically upload anything externally.
4. WP0 must support local bundle generation even if `hmm-info-exchange` does not exist.
5. Optional git commit/push to `hmm-info-exchange` must require explicit flags and must not store credentials.
6. WP0 must not export raw DuckDB files or full target/feature/score/exposure/event matrices.
7. WP0 must not consume prospective holdout.
8. WP0 must not train, refit, recalibrate, or change readiness.
9. WP0 must not create trading, buy/sell, sizing, recommendation, execution, or portfolio-action outputs.
10. WP0 must preserve invalidated-artifact warnings and must not use old pre-RERUN1 WP4-WP6 or old WP7-v1 artifacts as signal evidence.

## Expected Deliverables for GPT-EXCHANGE-WP0-v1

- `configs/gpt_info_exchange_policy_v1.yaml`
- `src/integrations/gpt_info_exchange.py`
- `scripts/export_gpt_info_exchange_bundle.sh`
- `scripts/gpt_info_exchange_gate.sh`
- `tests/test_gpt_info_exchange.py`
- `docs/runtime/GPT_INFO_EXCHANGE.md`
- `docs/runtime/GPT_PRO_SIGNAL_ANALYSIS_PROMPT.md`
- `reports/gpt_exchange/README.md`
- `reports/gpt_exchange/sample_manifest.json`
- `.gitignore` updates for live exchange outputs

## Revision Log

| date | change | by |
|---|---|---|
| 2026-06-12 | Activated GPT-EXCHANGE-WP0-v1 HMM info exchange bundle exporter package. | ChatGPT |
