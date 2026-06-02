# STAGE03_PREFLIGHT_EXECUTION_INDEX

Status: prepared, not Stage03 model work
Purpose: organize Stage03 preflight hardening work before Duration Hazard / BOCPD / Decision Engine starts.

## Validation Summary

The uploaded preflight plan is structurally valid and should be used as the hardening gate before Stage03. It correctly focuses on causal cache lineage, HMM cache contract, feature/state merge guards, HSMM as-of target safety, run atomicity, probability readiness, UI selection, universe/data lineage, evidence registry, and final preflight verdict.

Required adjustment: do not treat the legacy causal cache as fixed merely because a lineage table exists. The current cache lineage issue must remain fail-closed unless a native or strict inferred linkage exists. Stage03 preflight must also respect the Stage02 WP-E result.

## Execution Rules

1. Each package must use its own PR.
2. Do not implement Duration Hazard, BOCPD, Decision Engine, Robust HMM, Sticky HMM, or new training algorithms in these packages.
3. Every package must include synthetic tests.
4. Any lineage/readiness/run_status mismatch must fail closed.
5. No raw or calibrated `p_exit` may bypass readiness gates.
6. No in-sample state may be treated as causal state.
7. No external data fetch unless an explicit later data package allows it.
8. DuckDB/WAL files must not be committed.
9. Every package that uses the local DB must read `docs/runtime/LOCAL_DB_HANDOFF.md` first.

## Batches

| batch | file | contains | parallelism | stage03 blocking |
|---|---|---|---:|---:|
| Batch 00 | `STAGE03PF_BATCH_00_BASELINE_AND_LINEAGE.md` | WP0, WP1 | sequential | yes |
| Batch 01 | `STAGE03PF_BATCH_01_HMM_CACHE_LINEAGE.md` | WP2, WP3 | sequential after WP1 | yes |
| Batch 02 | `STAGE03PF_BATCH_02_HSMM_ASOF_ATOMICITY.md` | WP4, WP6, WP7, optional WP5 | WP4 and WP6 can run after WP0; WP7 after WP6; WP5 after WP4 | yes |
| Batch 03 | `STAGE03PF_BATCH_03_READINESS_UI_UNIVERSE_EVIDENCE.md` | WP8, WP9, WP10, WP11, optional WP12 | WP8 and WP10 can run after WP1/WP6; WP9 after WP8; WP11 after WP8/WP9 | mostly yes |
| Final | `STAGE03PF_BATCH_99_FINAL_GATE.md` | WP13 | after required P0/P1 packages | yes |

## Recommended Order

```text
WP0
→ WP1
→ WP2
→ WP3
→ WP4 and WP6 in parallel
→ WP7 after WP6
→ WP8 and WP10 in parallel
→ WP9 after WP8
→ WP11 after WP8/WP9
→ WP5 after WP4, can run before or alongside WP8/WP10
→ WP12 optional cleanup
→ WP13 final gate
```

## Current Activation Guidance

Do not mark true Stage03 as active until `Stage03PreflightVerdict: PASS` is produced.

Codex should be given one batch file at a time. If running in parallel, never exceed three active PRs and never cross a dependency boundary.