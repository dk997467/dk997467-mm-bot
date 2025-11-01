# Risk Register — Production Trading System

**Date:** 2025-11-01  
**System:** MM-Rebate Bot  
**Scope:** Top 10 Production Risks  
**Classification:** Probability × Impact → Priority

---

## Risk Scoring

- **Probability:** H (High >50%), M (Medium 20-50%), L (Low <20%)
- **Impact:** H (System down/$$$ loss), M (Degraded/$ loss), L (Minor/cosmetic)
- **Priority:** P0 (Critical), P1 (High), P2 (Medium), P3 (Low)

---

## Top 10 Risks

### 1. ⚠️ **Incomplete Order Cancellation on Freeze** — P0

**ID:** RISK-001  
**Category:** Risk & Limits  
**Probability:** H (60%)  
**Impact:** H (Uncontrolled positions, potential loss > $10k)  
**Priority:** **P0 (CRITICAL)**

**Description:**  
When freeze is triggered (edge < threshold), system attempts to cancel all open orders but lacks robust error handling. If exchange API fails or times out, orphaned orders may execute, leading to unintended positions and losses.

**Scenario:**
1. Edge drops below 1.5 BPS → freeze triggered
2. `cancel_all_orders()` called, but exchange returns 500 error
3. Some orders remain open on exchange
4. Orders fill during freeze → position exceeds limit
5. Risk monitor fails to detect (thinks orders are canceled)
6. Loss accumulates until manual intervention

**Evidence:**
- File: `tools/live/execution_loop.py` (cancel logic exists but not hardened)
- File: `tools/live/risk_monitor.py` (freeze triggers cancel)
- Test: `tests/integration/test_exec_bybit_risk_integration.py::test_freeze_triggers_cancel_all` (MISSING)

**Mitigations:**
1. ✅ **Implement robust `_cancel_all_open_orders()`:**
   ```python
   def _cancel_all_open_orders(self, trigger: str, mode="normal"):
       # 1. Try bulk cancel_all_orders() first
       # 2. Fall back to per-order cancel with retry
       # 3. Mark all as canceled in local store (assume success)
       # 4. Log summary with accurate canceled_count
       # 5. Trigger reconciliation to verify
   ```

2. Add integration test:
   ```bash
   pytest -q tests/integration/test_exec_bybit_risk_integration.py::test_freeze_triggers_cancel_all
   ```

3. Add monitoring alert: "Freeze triggered but >0 active orders after 30s"

4. Manual kill-switch: Allow operator to force-cancel via CLI

**Regression Gate:**
- Test: `test_freeze_triggers_cancel_all` (MUST PASS before prod)
- Alert: Freeze event → verify order count drops to 0 within 30s

**Owner:** `tools/live/execution_loop.py`, `tools/live/risk_monitor.py`  
**ETA:** 2-3 days  
**Status:** 🔴 **OPEN**

---

### 2. ⚠️ **Floating-Point Precision in Repricer** — P1

**ID:** RISK-002  
**Category:** Strategy  
**Probability:** M (40%)  
**Impact:** H (Incorrect prices, adverse selection)  
**Priority:** **P1 (HIGH)**

**Description:**  
Queue-aware repricer computes price adjustments (`delta_bps`) using floating-point math. Without directional rounding and proper clamping, computed prices may:
- Exceed `max_reprice_bps` limit due to FP error (bid becomes too high, ask too low)
- Violate bid < ask invariant
- Cause adverse selection (post too-aggressive prices)

**Scenario:**
1. Repricer computes `delta_bps = 0.9999999999` (should be 1.0)
2. After clamping to `max_reprice_bps = 1.0`, FP error persists
3. Bid price rounds up, ask rounds down → spread becomes negative
4. Exchange rejects order OR fills at unfavorable price
5. Adverse selection loss accumulates

**Evidence:**
- File: `strategy/repricer.py` (likely exists, not fully audited)
- Test: `tests/unit/test_queue_aware.py` (needs FP edge case tests)

**Mitigations:**
1. ✅ **Implement FP-safe clamp:**
   ```python
   def _clamp_delta_bps(delta: float, max_delta: float, direction: str) -> float:
       # direction = "bid" or "ask"
       clamped = min(abs(delta), max_delta)
       if direction == "bid":
           return math.floor(clamped * 100) / 100  # Round down for bids
       else:
           return math.ceil(clamped * 100) / 100   # Round up for asks
   ```

2. Add property-based test with Hypothesis:
   ```python
   @given(st.floats(min_value=0, max_value=10), st.floats(min_value=0.1, max_value=5))
   def test_clamp_never_exceeds_max(delta, max_delta):
       clamped_bid = _clamp_delta_bps(delta, max_delta, "bid")
       clamped_ask = _clamp_delta_bps(delta, max_delta, "ask")
       assert clamped_bid <= max_delta
       assert clamped_ask <= max_delta
   ```

3. Add sanity check before order placement: `assert bid < ask`

4. Log repricer decisions with full precision (aid debugging)

**Regression Gate:**
- Test: `test_clamp_never_exceeds_max` (property-based, 1000 examples)
- Test: `test_bid_ask_invariant` (no negative spreads)

**Owner:** `strategy/repricer.py`  
**ETA:** 3-4 days  
**Status:** 🟡 **OPEN**

---

### 3. ⚠️ **Config Manager Not Used** — P1

**ID:** RISK-003  
**Category:** Config Precedence  
**Probability:** M (50%)  
**Impact:** M (Wrong config applied, potential loss)  
**Priority:** **P1 (HIGH)**

**Description:**  
`tools/soak/config_manager.py` exists but is not imported by `tools/soak/run.py`. This means config precedence logic (CLI > Env > Override > Profile > Defaults) is not applied, and overrides may be silently ignored.

**Scenario:**
1. Operator sets `max_position_usd = 5000` in override JSON
2. `run.py` doesn't use `config_manager`, falls back to profile default (10000)
3. Bot trades with 2x intended position size
4. Risk limit breached, losses exceed expected

**Evidence:**
- File: `tools/soak/config_manager.py` (exists, 200+ lines)
- Grep: `config_manager` in `run.py` → NO MATCHES
- Test: `tests/integration/test_config_precedence_integration.py` (likely exists)

**Mitigations:**
1. ✅ **Import and use `config_manager` in `run.py`:**
   ```python
   from tools.soak import config_manager
   
   # In main():
   config = config_manager.load_config(
       profile=args.profile,
       overrides_path=args.overrides,
       env_prefix="MM_"
   )
   ```

2. Add integration test:
   ```python
   def test_overrides_take_precedence_over_profile():
       # Create profile with max_pos=10000
       # Create override with max_pos=5000
       # Assert final config.max_pos == 5000
   ```

3. Add config audit log at startup (show which source won for each key)

4. Validate config schema with Pydantic

**Regression Gate:**
- Test: `test_overrides_take_precedence_over_profile`
- Test: `test_cli_args_override_everything`
- Log: Config audit shows correct precedence

**Owner:** `tools/soak/run.py`, `tools/soak/config_manager.py`  
**ETA:** 1 day  
**Status:** 🟡 **OPEN**

---

### 4. ⚠️ **No Circuit Breaker for API Rate Limits** — P1

**ID:** RISK-004  
**Category:** Risk & Limits  
**Probability:** M (30%)  
**Impact:** H (Exchange ban, orders stuck)  
**Priority:** **P1 (HIGH)**

**Description:**  
System lacks circuit breaker for exchange API rate limits. If order rate exceeds exchange limits (e.g., Bybit: 10 orders/sec), API returns 429 errors, but system continues retrying without exponential backoff. Risk of temporary ban (1-24h), during which orders cannot be managed.

**Scenario:**
1. Market volatility → rapid repricing
2. System sends 50 orders/sec (5x limit)
3. Exchange returns 429 (rate limit exceeded)
4. System retries immediately → more 429s
5. Exchange bans API key for 1 hour
6. Open orders cannot be canceled during ban → exposed to market risk

**Evidence:**
- File: `tools/live/execution_loop.py` (no circuit breaker visible)
- Bybit docs: 10 orders/sec limit (https://bybit-exchange.github.io/docs/v5/rate-limit)

**Mitigations:**
1. ✅ **Implement circuit breaker:**
   ```python
   from tenacity import retry, stop_after_attempt, wait_exponential
   
   @retry(
       stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=4, max=60),
       reraise=True
   )
   def _place_order_with_breaker(self, order):
       response = self.exchange.place_order(order)
       if response.status_code == 429:
           self.circuit_breaker.trip()  # Pause all orders for 60s
           raise RateLimitError("Rate limit exceeded")
       return response
   ```

2. Add rate limiter (token bucket):
   ```python
   from ratelimit import limits, sleep_and_retry
   
   @sleep_and_retry
   @limits(calls=9, period=1)  # 9/sec (safety margin)
   def _rate_limited_place_order(self, order):
       return self._place_order_with_breaker(order)
   ```

3. Add monitoring: Alert on >5 rate limit errors/minute

4. Add manual override: CLI command to pause all orders

**Regression Gate:**
- Test: `test_circuit_breaker_trips_on_429`
- Test: `test_rate_limiter_enforces_max_calls_per_sec`
- Simulation: Flood test with 100 orders → verify max 9/sec

**Owner:** `tools/live/execution_loop.py`  
**ETA:** 3 days  
**Status:** 🟡 **OPEN**

---

### 5. ⚠️ **Volatility Calculation Not Using Log-Returns** — P2

**ID:** RISK-005  
**Category:** Strategy (Risk Guards)  
**Probability:** M (40%)  
**Impact:** M (Incorrect vol estimate, wrong freeze threshold)  
**Priority:** **P2 (MEDIUM)**

**Description:**  
Risk guards compute volatility using simple EMA of price changes, not log-returns. This underestimates true volatility for large price moves and can lead to:
- False sense of security (vol looks lower than it is)
- Late freeze triggering (edge already degraded)
- Incorrect risk ratio (vol used in P&L forecasting)

**Mathematical Issue:**
- Current: `Δ = P_t - P_{t-1}`, then EMA of `|Δ|`
- Correct: `r = log(P_t / P_{t-1})`, then `σ = stdev(r) × sqrt(252) × 10000` (annualized, in bps)

**Scenario:**
1. Price moves from $50,000 to $55,000 (+10%)
2. Current vol calc: `|55000 - 50000| / 50000 = 0.10` (10%)
3. Correct log-return: `log(55000/50000) = 0.0953` (9.53%, lower)
4. For small moves: difference negligible
5. For large moves (>5%): current method overestimates
6. Risk guard may trigger freeze prematurely or too late

**Evidence:**
- File: `tools/live/risk_guards.py` (likely exists, not fully audited)
- Test: `tests/unit/test_risk_guards.py` (needs log-return test)

**Mitigations:**
1. ✅ **Update volatility calculation:**
   ```python
   import math
   
   def _compute_vol_bps(prices: List[float]) -> float:
       log_returns = [math.log(prices[i] / prices[i-1]) 
                      for i in range(1, len(prices)) 
                      if prices[i-1] > 0]
       if not log_returns:
           return 0.0
       stdev = statistics.stdev(log_returns)
       ann_vol_bps = stdev * math.sqrt(252) * 10000
       return ann_vol_bps
   ```

2. Maintain backward-compatible property `vol_ema_bps` for tests

3. Add unit test:
   ```python
   def test_vol_uses_log_returns():
       prices = [100, 110, 105, 115]  # +10%, -4.5%, +9.5%
       vol = _compute_vol_bps(prices)
       # Expected: stdev of [log(1.1), log(0.955), log(1.095)]
       assert 1000 < vol < 5000  # reasonable range
   ```

4. Compare old vs new vol on historical data, ensure no regression

**Regression Gate:**
- Test: `test_vol_uses_log_returns`
- Test: `test_backward_compat_vol_ema_bps` (property still exists)
- Historical backtest: New vol matches academic calculation

**Owner:** `tools/live/risk_guards.py`  
**ETA:** 2-3 days  
**Status:** 🟡 **OPEN**

---

### 6. ⚠️ **Slow Integration Tests** — P2

**ID:** RISK-006  
**Category:** Tests/Flakiness  
**Probability:** L (20%)  
**Impact:** M (CI slowdown, developer friction)  
**Priority:** **P2 (MEDIUM)**

**Description:**  
Some integration tests take >5s each, slowing CI and developer feedback loops. Long-running tests increase risk of timeouts and flakiness.

**Evidence:**
- Observation: Integration tests sometimes take >30s total
- No timeout enforcement (`pytest.ini` lacks `timeout`)

**Mitigations:**
1. Add timeout decorator:
   ```python
   @pytest.mark.timeout(10)
   def test_slow_integration():
       ...
   ```

2. Profile slow tests:
   ```bash
   pytest --durations=10 tests/integration
   ```

3. Optimize slow tests (mock external calls, use smaller datasets)

4. Consider splitting into `@pytest.mark.slow` for optional execution

**Regression Gate:**
- Metric: `pytest --durations=0` → no test >10s
- CI: Add timeout to GH Actions (`timeout-minutes: 15`)

**Owner:** `tests/`, `pytest.ini`  
**ETA:** 3 days  
**Status:** 🟡 **OPEN**

---

### 7. ⚠️ **No Lockfile for Dependencies** — P2

**ID:** RISK-007  
**Category:** Dependencies  
**Probability:** M (30%)  
**Impact:** M (Non-reproducible builds, version drift)  
**Priority:** **P2 (MEDIUM)**

**Description:**  
No `requirements.lock` or `poetry.lock` file. Dependency versions can drift between environments (dev, CI, prod), causing:
- "Works on my machine" bugs
- CI/prod version mismatch
- Security vulnerabilities from auto-upgraded deps

**Mitigations:**
1. Generate lockfile:
   ```bash
   pip freeze > requirements.lock
   ```

2. Use in CI:
   ```bash
   pip install -r requirements.lock
   ```

3. Add Dependabot for security updates

4. Document: "Always regenerate requirements.lock after adding deps"

**Regression Gate:**
- File: `requirements.lock` exists
- CI: Uses `requirements.lock` instead of `requirements.txt`
- Test: `pip install -r requirements.lock` succeeds

**Owner:** `requirements.lock` (new file)  
**ETA:** 1 day  
**Status:** 🟡 **OPEN**

---

### 8. ⚠️ **No SLA Monitoring** — P2

**ID:** RISK-008  
**Category:** Performance/Latency  
**Probability:** M (30%)  
**Impact:** M (Undetected degradation)  
**Priority:** **P2 (MEDIUM)**

**Description:**  
Latency is tracked (p95, p99) but no SLA enforcement or alerts. If latency degrades gradually (e.g., 200ms → 400ms over days), system may not detect until performance is critically impaired.

**Mitigations:**
1. Add Prometheus alerting rules:
   ```yaml
   - alert: HighLatencyP95
     expr: histogram_quantile(0.95, rate(mm_latency_ms_bucket[5m])) > 340
     for: 5m
     annotations:
       summary: "Latency p95 > 340ms for 5 minutes"
   ```

2. Add Grafana dashboard with SLA lines

3. Daily SLA report (% of time within SLA)

**Regression Gate:**
- Alert: Fires when p95 > 340ms for 5m
- Dashboard: Shows SLA compliance %

**Owner:** `monitoring/`, `tools/obs/`  
**ETA:** 2 days  
**Status:** 🟡 **OPEN**

---

### 9. ⚠️ **Rust Order Book Build Dependency** — P3

**ID:** RISK-009  
**Category:** Dependencies  
**Probability:** L (15%)  
**Impact:** M (Build failures in new environments)  
**Priority:** **P3 (LOW)**

**Description:**  
`mm-orderbook` Rust extension assumes local build (`file:rust`). If build environment lacks Rust toolchain or maturin, install fails silently or with cryptic error.

**Mitigations:**
1. Document Rust build requirements in README
2. Add CI check for Rust toolchain
3. Provide pre-built wheels for common platforms
4. Add graceful fallback to Python-only order book (slower)

**Regression Gate:**
- Test: `python -c "import mm_orderbook"` succeeds in clean env
- CI: Fresh container builds successfully

**Owner:** `rust/`, `pyproject.toml`  
**ETA:** 5 days  
**Status:** 🟡 **OPEN**

---

### 10. ⚠️ **No Load Testing** — P3

**ID:** RISK-010  
**Category:** Performance  
**Probability:** L (10%)  
**Impact:** M (Production slowdown under load)  
**Priority:** **P3 (LOW)**

**Description:**  
No load/stress testing performed. Unknown how system behaves under high order volume (e.g., 1000 orders/min, 10 symbols).

**Mitigations:**
1. Create load test harness (Locust or custom)
2. Simulate: 10 symbols, 100 orders/min, 1h duration
3. Measure: latency, memory, CPU, order success rate
4. Identify bottlenecks (order book updates, network I/O)

**Regression Gate:**
- Test: Load test completes without errors
- Metric: p95 latency < 340ms under load

**Owner:** `tools/perf/`  
**ETA:** 1-2 weeks  
**Status:** 🟡 **OPEN**

---

## Risk Summary Matrix

| Priority | Count | Total Impact |
|----------|-------|--------------|
| **P0 (CRITICAL)** | 1 | High (system stability) |
| **P1 (HIGH)** | 3 | High (correctness, config, limits) |
| **P2 (MEDIUM)** | 4 | Medium (quality, observability) |
| **P3 (LOW)** | 2 | Low (build, perf validation) |

---

## Risk Heatmap

```
        PROBABILITY
        L    M    H
    ┌────┬────┬────┐
  H │    │ 2,4│ 1  │ IMPACT
    ├────┼────┼────┤
  M │ 9  │ 5,7│ 3  │
    │    │ 8  │    │
    ├────┼────┼────┤
  L │ 10 │ 6  │    │
    └────┴────┴────┘

Legend:
1 = Incomplete cancel-all (P0)
2 = FP precision (P1)
3 = Config manager (P1)
4 = Circuit breaker (P1)
5 = Volatility calc (P2)
6 = Slow tests (P2)
7 = No lockfile (P2)
8 = No SLA monitoring (P2)
9 = Rust build (P3)
10 = No load test (P3)
```

---

## Next Steps

1. **Immediate (This Week):**
   - RISK-001: Implement cancel-all hardening
   - RISK-003: Import config_manager in run.py

2. **Short-Term (Next 2 Weeks):**
   - RISK-002: Add FP-safe clamp to repricer
   - RISK-004: Implement circuit breaker
   - RISK-005: Update volatility calculation

3. **Medium-Term (Next Month):**
   - RISK-006 through RISK-010

---

**Risk Register Maintained By:** Principal Engineer  
**Next Review:** 2025-11-08 (weekly)  
**Escalation:** P0/P1 risks blocked → escalate to CTO

*Last Updated: 2025-11-01 17:45 UTC*

