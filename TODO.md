# TODO List

## Completed
- [x] coroutine_misuse_fix: Find and fix coroutine misuse around Recorder
- [x] pytest_ini_markers: Update pytest.ini with markers section for slow tests
- [x] test_legacy_methods_await: Fix test_legacy_methods to await record_orderbook and record_trade calls
- [x] verify_production_code: Verify production code uses asyncio.create_task for recorder calls
- [x] verify_test_awaits: Verify all test recorder.record_* calls are properly awaited
- [x] run_tests: Run pytest -q to verify all fixes work
- [x] dry_run_fixes: Fix dry-run connectors, health/metrics guards, and tick simulator
- [x] timezone_imports_fix: Fix missing timezone imports and replace utcnow()
- [x] prometheus_metrics_unify: Unify Prometheus metrics to label-less counters/gauges
- [x] harden_metrics_update: Harden metrics update call sites with validation
- [x] metrics_symbol_safety: Ensure symbol handling is safe strings in MetricsExporter
- [x] strategy_quote_improvements: Update strategy with level capping, refresh throttling, and safe metrics
- [x] order_manager_amend_create: Add lightweight "amend-or-create" with rate limiting and backoff

## Pending
- [ ] Wire strategy to call place_or_amend instead of plain create
