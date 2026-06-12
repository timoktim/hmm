# CODEX_STAGE03V_PHASE2_WP0_signal_panel_contract

Repository: `timoktim/hmm`

Index id: `STAGE03V-PHASE2-WP0-v1`

Work package: `docs/work_packages/stage03v/STAGE03V_PHASE2_WP0_signal_panel_contract.md`

Suggested branch: `stage03v/phase2-wp0-signal-panel-contract`

## Instruction

Start from updated `main`. Confirm PR91 / `STAGE03V-CLOSEOUT1-v1` has been merged and that closeout artifacts are present and pass:

```text
reports/stage03v/stage03v1_phase1_closeout_report.json
reports/stage03v/stage03v1_phase2_handoff.json
reports/stage03v/stage03v1_artifact_freeze_manifest.json
reports/stage03v/stage03v1_invalidated_artifact_registry.json
```

Then execute only this work package:

```text
docs/work_packages/stage03v/STAGE03V_PHASE2_WP0_signal_panel_contract.md
```

## Required outcome

Implement the first Stage03V Phase 2 signal panel:

```text
src/signals/signal_panel_snapshot.py
src/ui/signal_panel_page.py
navigation entry: 当前状态 / 信号面板
```

The panel must be baseline-first and research-only:

```text
primary layer: realized-volatility baseline risk band
context layers: HMM state and HSMM lifecycle
Stage03V layer: readiness-gated risk tendency; numeric probability only if current per-entity calibrated score source exists
model role: research_only_hazard_overlay
```

## Boundary reminders

Do not:

```text
train, refit, or tune models
recalibrate probabilities
consume or evaluate prospective holdout
modify target definitions, readiness thresholds, folds, buckets, or exposure rules
implement Stage03V2 or Stage03V3
create buy/sell/position-sizing/recommendation/execution/portfolio-action outputs
synthesize sector-level calibrated probabilities from aggregate reports
use invalidated pre-RERUN1 WP4-WP6 or old WP7-v1 artifacts as signal sources
```

If no current per-entity calibrated score source exists, show readiness metadata and `unavailable_current_per_entity_score_source`; do not fabricate probability values.

Use the return format specified in the work package when opening the PR.
