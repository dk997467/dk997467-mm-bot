Reports Overview
================

## Report Types and Locations

### CANARY Reports
- **Location**: `artifacts/REPORT_CANARY.md`
- **Purpose**: Canary deployment validation
- **Fields**: deployment status, metrics comparison, go/no-go decision
- **Format**: Markdown table, ASCII

### SIM Reports  
- **Location**: `artifacts/REPORT_SIM.md`
- **Purpose**: Live simulation results
- **Fields**: PnL, latency, fill rates, risk metrics
- **Format**: JSON + Markdown summary

### BACKTEST Reports
- **Location**: `artifacts/BACKTEST_REPORT.json`, `artifacts/BACKTEST_REPORT.md`
- **Purpose**: Historical strategy validation
- **Fields**: returns, drawdown, Sharpe, trade statistics
- **Format**: Deterministic JSON + Markdown tables

### EDGE Reports
- **Location**: `artifacts/EDGE_REPORT.json`, `artifacts/EDGE_REPORT.md`
- **Purpose**: Edge component breakdown
- **Fields**: gross_bps, fees_eff_bps, adverse_bps, slippage_bps, inventory_bps, net_bps
- **Format**: JSON (sorted keys) + fixed-format MD table

### RECONCILE Reports
- **Location**: `dist/finops/<YYYYMMDD_Z>/reconcile_report.json`, `reconcile_diff.md`
- **Purpose**: Exchange reconciliation
- **Fields**: by-symbol deltas, totals, acceptable tolerance ≤1e-8
- **Format**: Deterministic JSON + ASCII table

### WEEKLY ROLLUP
- **Location**: `artifacts/WEEKLY_ROLLUP.json`, `artifacts/WEEKLY_ROLLUP.md`
- **Purpose**: Weekly aggregation of soak metrics and ledger
- **Fields**: edge_net_bps (median/p25/p75/trend), order_age_p95_ms (median/p90/trend), taker_share_pct (median/p90/trend), ledger (equity_change/fees/rebates), regress_guard, verdict
- **Format**: Deterministic JSON + ASCII table

## Reading Reports

### Quick Health Check
```bash
make go-nogo  # Checks all key thresholds
```

### Individual Reports
```bash
make edge     # Generate edge breakdown
make finops   # Generate reconciliation
make region   # Generate region comparison
```

### Report Validation
- All JSON: `ensure_ascii=True, sort_keys=True, separators=(",", ":")`
- All files end with `\n`
- Markdown tables use fixed `%.6f` number formatting
- TOTAL rows appear last in tables
