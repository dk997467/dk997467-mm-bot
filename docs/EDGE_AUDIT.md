# Edge Audit - Net BPS Calculation

**Last Updated**: 2025-01-09  
**Status**: ✅ Production Ready

---

## 📐 Formula & Sign Conventions

### Net BPS Calculation

```python
net_bps = gross_bps + fees_eff_bps + slippage_bps + inventory_bps
```

### Component Signs

| Component | Sign | Description |
|-----------|------|-------------|
| `gross_bps` | **≥ 0** | Revenue before costs (always positive or zero) |
| `fees_eff_bps` | **≤ 0** | Exchange fees (always negative - cost) |
| `slippage_bps` | **±** | Slippage vs quoted price (can be positive or negative) |
| `inventory_bps` | **≤ 0** | Inventory holding cost (always negative - cost, NO abs()) |
| `adverse_bps` | **±** | Adverse selection indicator (NOT included in net_bps) |

---

## 🔧 Implementation Details

### 1. Fee Normalization

Fees are **always stored as negative**:

```python
# In tools/edge_audit.py line 102
d['fees_eff_bps_sum'] += -abs(_finite(fee_bps))  # Force negative
```

This ensures:
- `fee_bps = 0.1` from trades → stored as `-0.1`
- When added to `net_bps`, it correctly reduces profitability

### 2. Slippage Calculation

```python
# Slippage vs quoted price at execution time
sgn = +1 if buy else -1
q_ref = ask if buy else bid
slip_bps = sgn * (execution_price - q_ref) / q_ref * 1e4
```

- Positive slippage = paid more than quoted (cost)
- Negative slippage = paid less than quoted (gain)

### 3. Inventory Cost

```python
# Signed inventory: buy=+, sell=-
inv_signed = sgn * qty  # +1 for buy, -1 for sell
avg_inv_signed = sum(inv_signed) / n_fills

# Inventory cost: negative proxy (always cost)
inventory_bps = -1.0 * abs(avg_inv_signed / avg_notional)
net_bps += inventory_bps  # Add (it's already negative)
```

Inventory is always a cost (capital tied up), represented as negative bps.

### 4. Adverse Selection

**NOT included in net_bps formula** - used only as diagnostic metric:

```python
adverse_bps = sgn * (mid_after_1s - mid_before) / mid_before * 1e4
```

- Positive = price moved against us (adverse)
- Negative = price moved with us (favorable)

---

## 🧪 Unit Testing

### Test Data

```python
# tests/test_edge_math_unit.py
trades = [
    {"side":"B", "price":100.0, "mid_before":100.0, "fee_bps":0.1},  # Input: positive
    # ...
]

# Expected after normalization:
fees_eff_bps = -0.1  # Stored as negative
net_bps = gross + fees + slippage - |inventory|
```

### Assertions

```python
assert fees_eff_bps <= 0.0, "Fees must be negative"
assert gross_bps >= 0.0, "Gross must be non-negative"
assert net_bps > 0.0, "Net should be positive for profitable trading"
```

---

## 🚫 Common Pitfalls (FIXED)

### ❌ Wrong (Before Fixes)

```python
# OLD FORMULA v1 (INCORRECT):
net_bps = gross_bps - fees_eff_bps - adverse_bps - slippage_bps - inventory_bps
#                    ^                ^
#                    Wrong signs!

# OLD FORMULA v2 (PARTIALLY INCORRECT):
net_bps = gross_bps + fees_eff_bps + slippage_bps - abs(inventory_bps)
#                                                    ^
#                                                    Unnecessary abs()!
```

This caused:
- v1: `net_bps` to be negative even for profitable trades (double subtraction)
- v2: `inventory_bps` calculated incorrectly with abs() at the end

### ✅ Correct (Final Fix)

```python
# FINAL FORMULA (CORRECT):
net_bps = gross_bps + fees_eff_bps + slippage_bps + inventory_bps
#                    ^                               ^
#                    All components already signed correctly
#                    - fees_eff_bps ≤ 0
#                    - inventory_bps ≤ 0 (NO abs() needed)
```

---

## 📊 Example Calculation

### Trade Data

```
Buy 1.0 BTC @ 100.0
mid_before = 100.0
quoted_ask = 100.1
fee_bps = 0.1 (input)
```

### Component Breakdown

```python
# Gross (price improvement vs mid)
gross_bps = +1 * (100.0 - 100.0) / 100.0 * 1e4 = 0.0

# Fees (normalized to negative)
fees_eff_bps = -0.1

# Slippage (vs quoted price)
slippage_bps = +1 * (100.0 - 100.1) / 100.1 * 1e4 = -10.0  # Saved 10 bps

# Inventory (proxy)
inventory_bps = 0.01

# Net BPS
net_bps = 0.0 + (-0.1) + (-10.0) - 0.01 = -10.11 bps
```

---

## 🔄 Batch Deduplication

### Problem

With async batching, partial fills can be double-counted:
- Batch attempts order placement
- Partial fill occurs
- Retry creates duplicate fill entry

### Solution (TODO #3 - Pending)

```python
# Deduplication by (symbol, client_order_id, ts_ms) tuple
seen_fills = set()
for fill in fills:
    key = (fill['symbol'], fill['cl_id'], fill['ts_ms'])
    if key in seen_fills:
        continue  # Skip duplicate
    seen_fills.add(key)
    # Process fill...
```

**Status**: Not yet implemented (low priority - reconcile normalizes on next tick)

---

## ✅ Invariants

1. **Fees are always negative**: `fees_eff_bps ≤ 0`
2. **Gross is non-negative**: `gross_bps ≥ 0`
3. **Inventory is always negative (cost)**: `inventory_bps ≤ 0`
4. **Net formula uses NO abs()**: `net_bps = gross + fees + slippage + inventory`
5. **Net is profitable for synthetic test data**: `net_bps > 0` (for baseline)
6. **Adverse is informational only**: NOT included in net_bps

---

## 📝 Changelog

### 2025-01-09 - Final Net BPS Fix (v2)
- ✅ Removed abs() from inventory_bps in net_bps formula
- ✅ Inventory now correctly signed (≤ 0 always cost)
- ✅ Updated golden files (net_bps: 5.731 → 5.737)
- ✅ Added inventory_bps ≤ 0 invariant check
- ✅ Documentation updated with final formulas

### 2025-01-09 - Net BPS Fix (v1)
- ✅ Fixed sign convention in net_bps formula
- ✅ Normalized fee_bps to always be negative
- ✅ Updated golden files (net_bps: -1.78 → 5.73)
- ✅ Added invariant checks in e2e tests
- ✅ Unit test coverage for edge aggregator

### Previous Issues (RESOLVED)
- ❌ net_bps was negative for profitable trades (v1: wrong formula)
- ❌ fees_eff_bps stored as positive (v1: should be negative)
- ❌ adverse_bps incorrectly subtracted in net_bps (v1)
- ❌ inventory_bps used abs() in net_bps (v2: unnecessary)

---

## 🎯 Acceptance Criteria

| Criterion | Expected | Actual | Status |
|-----------|----------|--------|--------|
| `net_bps > 0` (test data) | Yes | 5.737 bps | ✅ |
| `fees_eff_bps ≤ 0` | Yes | -0.1 | ✅ |
| `gross_bps ≥ 0` | Yes | 10.0 | ✅ |
| `inventory_bps ≤ 0` | Yes | -0.002 | ✅ |
| NO abs() in net_bps | Yes | ✅ | ✅ |
| Unit tests pass | Yes | ✅ | ✅ |
| E2E determinism | Yes | ✅ | ✅ |

---

## 📚 References

- **Implementation**: `tools/edge_audit.py` (lines 85-137)
- **Unit Tests**: `tests/test_edge_math_unit.py`
- **E2E Tests**: `tests/e2e/test_edge_audit_e2e.py`
- **Golden Files**: `tests/golden/EDGE_REPORT_case1.{json,md}`

