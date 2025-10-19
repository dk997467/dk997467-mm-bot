# STEP 1 — Baseline Shadow (Real Feed) + Auto-Tune

**Timestamp:** 2025-10-19 15:23:58 UTC  
**Iterations:** 6 windows  
**Exchange:** bybit  
**Symbols:** BTCUSDT, ETHUSDT  
**Profile:** moderate  

---

## KPI Summary (Averages)

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| maker_taker_ratio | ≥ 0.83 | 0.000 | ❌ |
| net_bps | ≥ 2.5 | 0.00 | ❌ |
| p95_latency_ms | ≤ 350 | 6180.2 | ❌ |
| risk_ratio | ≤ 0.40 | 0.800 | ❌ |

---

## Auto-Tune Attempts

### Attempt 1: Baseline

- touch_dwell_ms: 25
- min_lot: 0.001
- Result: FAIL
- maker_taker: 0.000
- net_bps: 0.00
- latency: 6236.3ms
- risk: 0.800

### Attempt 2: Attempt A

- touch_dwell_ms: 35
- min_lot: 0.001
- Result: FAIL
- maker_taker: 0.000
- net_bps: 0.00
- latency: 6265.4ms
- risk: 0.800

### Attempt 3: Attempt B

- touch_dwell_ms: 45
- min_lot: 0.005
- Result: FAIL
- maker_taker: 0.000
- net_bps: 0.00
- latency: 6263.9ms
- risk: 0.800

### Attempt 4: Attempt C

- touch_dwell_ms: 45
- min_lot: 0.01
- Result: FAIL
- maker_taker: 0.000
- net_bps: 0.00
- latency: 6180.2ms
- risk: 0.800

---

## Decision

### ❌ **NO-GO**

KPI thresholds not met:

- maker_taker_ratio: 0.000 < 0.83
- net_bps: 0.00 < 2.5
- p95_latency_ms: 6180.2 > 350
- risk_ratio: 0.800 > 0.4

**Recommendations:**
1. Review market conditions (volatility, liquidity)
2. Try different symbols (e.g., SOLUSDT, AVAXUSDT)
3. Increase iterations (e.g., 96 windows)
4. Use Redis integration for prod-identical feed (Step 3)

---

**Generated:** 2025-10-19 15:23:58 UTC  
**Report Path:** `reports\analysis\STEP1_BASELINE_SUMMARY.md`  
