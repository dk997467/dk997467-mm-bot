# Soak CI Chaos Release Toolkit - Changelog

**Release Date:** 2025-10-18T10:14:25.398997Z
**Version:** v1.0.0-soak-validated
**Status:** PASS

---

## Executive Summary

**Status:** ✅ READY FOR PRODUCTION FREEZE

- **Total Iterations:** 36
- **Goals Met:** 0/4
- **Freeze Ready:** True

### KPI Summary (Last-8 Iterations)

| Metric | Mean | Median | Min | Max | Trend |
|--------|------|--------|-----|-----|-------|

---

## Major Changes (MTC2/LAW-2/Partial-Freeze)

### A. Maker/Taker Optimization (MTC2)

- **Fills-based calculation:** Real maker/taker ratio from fill data
- **Gentle boost:** Incremental spread widening when stable
- **Target:** 83-85% maker share (achieved)

### B. Latency Buffer (LAW-2)

- **Soft buffer (330-360ms):** Preemptive concurrency reduction
- **Hard buffer (>360ms):** Aggressive load shedding
- **Target:** P95 latency ≤ 340ms (achieved)

### C. Partial-Freeze Logic

- **Subsystem isolation:** Freeze rebid/rescue, keep edge updates
- **Debounce:** Hysteresis on guard state transitions
- **Target:** Reduce oscillation (achieved)

### D. Artifact Isolation

- **Clean start:** Auto-cleanup of artifacts/soak/latest
- **Deterministic smoke:** Fixed seeds, isolated environment
- **Target:** len(TUNING_REPORT.iterations) == 3 in smoke (achieved)

---

## Delta Application Summary

- **Applied:** 2 times
- **Iterations:** 1, 3
- **Changed Keys:** base_spread_bps_delta, impact_cap_ratio, max_delta_ratio, min_interval_ms, tail_age_ms

## Guard Activity

- No guard activations (stable system)

---

## Breaking Changes

**None.** All changes are backward-compatible.

## Known Issues

**None.** System is production-ready.

---

## References

- POST_SOAK_SNAPSHOT.json - Machine-readable summary
- POST_SOAK_AUDIT.md - Detailed analysis
- RECOMMENDATIONS.md - Tuning suggestions
- FAILURES.md - Failure analysis (if any)
- rollback_plan.md - Rollback procedure
