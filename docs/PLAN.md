# Market Maker Bot Optimization Plan
## Branch: mm-optimizations

### Repository Structure Analysis
```
mm-bot/
├── src/
│   ├── strategy/          # Core quoting logic (Avellaneda-Stoikov inspired)
│   ├── execution/         # Order management & placement
│   ├── risk/             # Position limits & loss monitoring
│   ├── connectors/       # Bybit REST/WebSocket APIs
│   ├── marketdata/       # Order book processing
│   ├── storage/          # Data persistence (Parquet/SQLite/PG)
│   ├── metrics/          # Prometheus monitoring
│   └── common/           # Config, models, utils
├── tests/                # Comprehensive test suite
├── monitoring/           # Grafana dashboards, Prometheus
├── cli/                  # Command-line tools
└── config.yaml           # Strategy parameters
```

**Current State**: Production-ready HFT bot with basic market making, risk controls, and monitoring. Uses Rust-backed L2 order book, adaptive spreads, inventory skew.

---

## 🚨 CRITICAL GAPS (≤15 bullets)

### Profit Logic (High Impact)
1. **Missing maker rebate optimization** - No dynamic spread adjustment for Bybit's tiered rebate structure
2. **Inefficient inventory skew** - Linear skew doesn't account for volatility clustering
3. **Static volatility lookback** - 30s window too short for regime detection
4. **Missing market impact modeling** - No consideration of order size vs. liquidity depth

### Risk Management (Critical)
5. **No dynamic position sizing** - Fixed USD limits ignore market conditions
6. **Inadequate kill-switch triggers** - Only daily loss, missing drawdown/volatility spikes
7. **No circuit breaker** - Missing market-wide stress detection

### Execution Quality (High Impact)
8. **Inefficient order refresh** - Fixed 800ms refresh ignores market activity
9. **Missing fill prediction** - No ML-based fill probability estimation
10. **No order book toxicity detection** - Missing predatory trading detection
11. **Inefficient amend-or-create** - Current implementation has race conditions

### Monitoring & Alerting (Medium Impact)
12. **No P&L attribution** - Can't identify which strategy components are profitable
13. **Missing latency breakdown** - No end-to-end latency profiling
14. **No market regime detection** - Missing volatility/trend regime classification

### Data & Backtesting (Medium Impact)
15. **No regime-aware backtesting** - Missing stress testing across market conditions

---

## 📁 EXACT FILE-LEVEL CHANGES

### Phase 1: Profit Logic & Risk (Week 1-2)
```
src/strategy/quoting.py
├── Add maker_rebate_tiers: Dict[int, float]  # Bybit tier structure
├── Implement dynamic_spread_adjustment()      # Adjust for rebate optimization
├── Add regime_detection()                    # Volatility EWMA tertiles
├── Implement volatility_aware_skew()         # Regime-based inventory skew
└── Add market_impact_model()                 # Order size vs. liquidity analysis

src/risk/risk_manager.py
├── Add dynamic_position_sizing()             # Market volatility-adjusted limits
├── Implement circuit_breaker()               # Market-wide stress detection
└── Add regime_aware_limits()                 # Volatility-adjusted risk limits

src/common/config.py
├── Add StrategyConfig.maker_rebate_tiers: Dict[int, float]
├── Add StrategyConfig.regime_detection_window: int = 300
├── Add StrategyConfig.volatility_ewma_alpha: float = 0.1
├── Add RiskConfig.dynamic_position_multiplier: float = 1.0
└── Add RiskConfig.circuit_breaker_thresholds: Dict[str, float]
```

### Phase 2: Execution Quality (Week 3-4)
```
src/execution/order_manager.py
├── Fix amend_or_create_race_conditions()     # Atomic order operations
├── Implement fill_probability_estimator()    # ML-based fill prediction
├── Add order_book_toxicity_detector()       # Predatory trading detection
└── Add adaptive_refresh_timing()             # Market activity-based refresh

src/marketdata/orderbook.py
├── Add toxicity_indicators()                 # Order flow toxicity metrics
├── Implement microprice_drift_detection()    # 200-400ms drift >3bps
├── Add order_book_imbalance_calculator()    # OB imbalance >0.65
└── Add aggressor_ratio_tracker()             # Buy ratio >0.7 in last 50 trades
```

### Phase 3: Monitoring & Analytics (Week 5-6)
```
src/metrics/exporter.py
├── Add pnl_attribution_metrics()             # Strategy component P&L
├── Implement latency_breakdown()             # End-to-end latency profiling
├── Add regime_classification_metrics()       # Market regime indicators
└── Add toxicity_detection_metrics()          # Toxicity event counters

src/storage/recorder.py
├── Add high_frequency_tick_recording()       # Sub-second event capture
├── Implement data_compression_optimization() # Zstandard level tuning
└── Add data_retention_policies()             # Time-based data archiving

monitoring/grafana/
├── Create mm_bot_profitability.json          # P&L attribution dashboard
├── Create mm_bot_execution_quality.json      # Execution metrics dashboard
└── Create mm_bot_risk_analytics.json         # Risk metrics dashboard
```

### Phase 4: Data & Backtesting (Week 7-8)
```
src/backtesting/
├── Create regime_aware_backtester.py         # Market condition simulation
├── Implement stress_testing.py               # Extreme market scenario testing
└── Create performance_attribution.py          # Strategy component analysis

tests/
├── Add test_regime_detection.py              # Regime detection tests
├── Add test_toxicity_detection.py            # Toxicity detection tests
├── Add test_dynamic_position_sizing.py       # Dynamic sizing tests
└── Add test_stress_scenarios.py              # Stress testing validation
```

---

## ✅ ACCEPTANCE CRITERIA & KPIs

### Profitability Metrics
- **Maker rebate capture**: >95% of orders qualify for highest rebate tier
- **Spread efficiency**: Reduce effective spread by 15-20% through rebate optimization
- **Hit rate**: ≥1-3% (realistic market making expectations)
- **Maker share**: ≥90% (post-only enforcement)

### Risk Management KPIs
- **Dynamic sizing**: Position limits adjust within 30s of volatility regime change
- **Circuit breaker**: Trigger within 5s of market stress detection
- **Net P&L**: >0 after fees (sustainable profitability)

### Execution Quality Metrics
- **Cancel rate**: ≤80% without rate-limit breaches
- **Latency reduction**: P95 quote→ACK <300ms (from current 50ms)
- **Order efficiency**: Reduce order refresh frequency by 40% through adaptive timing
- **Toxicity detection**: Identify predatory trading within 100ms

### Monitoring & Alerting KPIs
- **P&L attribution**: Real-time breakdown with <1s latency
- **Regime detection**: Classify market conditions within 10s of regime change
- **Alert accuracy**: <5% false positive rate on risk alerts

### Data & Backtesting KPIs
- **Regime coverage**: Backtest across 3 market regimes (low/normal/high volatility)
- **Stress test scenarios**: 5+ extreme market condition simulations
- **Performance attribution**: >90% of P&L variance explained by strategy components
- **Data compression**: Reduce storage footprint by 60% through Zstandard optimization

---

## 🔍 PRECISE DEFINITIONS

### Toxicity Detection
```python
# Toxicity = any of these conditions:
toxicity_conditions = {
    "microprice_drift": "drift_bps > 3.0 over 200-400ms window",
    "orderbook_imbalance": "|bid_depth - ask_depth| / total_depth > 0.65",
    "aggressor_ratio": "buy_aggressor_count / total_trades > 0.7 in last 50 trades"
}
```

### Market Regimes
```python
# Regimes = volatility EWMA tertiles affecting strategy parameters:
regime_configs = {
    "low_vol": {
        "spread_clamp_bps": 0.5,
        "levels_per_side": 5,
        "position_multiplier": 1.2
    },
    "normal_vol": {
        "spread_clamp_bps": 1.0,
        "levels_per_side": 3,
        "position_multiplier": 1.0
    },
    "high_vol": {
        "spread_clamp_bps": 2.0,
        "levels_per_side": 2,
        "position_multiplier": 0.7
    }
}
```

---

## 🚀 IMPLEMENTATION ROADMAP

### Week 1-2: Foundation
- Implement maker rebate optimization
- Add regime detection framework (EWMA tertiles)
- Implement dynamic position sizing

### Week 3-4: Execution
- Fix amend-or-create race conditions
- Implement toxicity detection (3 specific conditions)
- Add adaptive refresh timing

### Week 5-6: Monitoring
- Build P&L attribution system
- Create advanced dashboards
- Implement regime classification metrics

### Week 7-8: Validation
- Comprehensive backtesting across regimes
- Stress testing validation
- Performance optimization

### Success Metrics
- **Phase 1**: 15-20% improvement in maker rebate capture
- **Phase 2**: 20-25% reduction in effective spreads
- **Phase 3**: Real-time P&L attribution with <1s latency
- **Phase 4**: Comprehensive backtesting across 3 volatility regimes

---

## 📋 DELIVERABLES PER PHASE

### Phase 1 Deliverables
- **Code**: PR-style diffs for quoting.py, risk_manager.py, config.py
- **Tests**: Unit tests for regime detection and dynamic sizing
- **Config**: Updated config.yaml with new parameters
- **Docs**: README updates for new features

### Phase 2 Deliverables
- **Code**: PR-style diffs for order_manager.py, orderbook.py
- **Tests**: Unit tests for toxicity detection and race condition fixes
- **Metrics**: New Prometheus metrics for toxicity events
- **Docs**: Runbook for toxicity detection configuration

### Phase 3 Deliverables
- **Code**: PR-style diffs for metrics/exporter.py, storage/recorder.py
- **Dashboards**: 3 new Grafana dashboard JSONs
- **Tests**: Integration tests for P&L attribution
- **Docs**: Monitoring and alerting runbook

### Phase 4 Deliverables
- **Code**: New backtesting framework
- **Tests**: Comprehensive backtesting validation tests
- **Docs**: Backtesting runbook and performance analysis guide
- **Validation**: Performance regression test suite

---

## 🔧 TECHNICAL CONSTRAINTS

- **No new external dependencies**: Use existing libraries (numpy, polars, prometheus_client)
- **Feature flags**: All new behavior behind config flags
- **Backward compatibility**: Maintain existing API contracts
- **Performance**: P95 quote→ACK <300ms target
- **Memory**: <2GB RAM usage under normal operation
- **Storage**: <100MB/day data generation with compression

---

## 📊 EXPECTED ROI

- **Maker rebate optimization**: +15-25% improvement in fee capture
- **Regime-aware strategy**: +25% P&L during volatile periods
- **Toxicity detection**: +20% fill rate improvement through predatory trading avoidance
- **Dynamic risk management**: +30% capital efficiency
- **Overall expected improvement**: +40-60% in risk-adjusted returns
