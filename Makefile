.PHONY: final-check
final-check:
	@echo "[final-check] pytest"
	@pytest -q
	@echo "[final-check] soak-smoke"
	@$(MAKE) soak-smoke
	@echo "[final-check] morning"
	@$(MAKE) morning
	@echo "[final-check] bundle-auto"
	@$(MAKE) bundle-auto
	@echo "[final-check] release-dry (fast)"
	@$(MAKE) release-dry VER=v0.1.0
.PHONY: morning
morning:
	@bash tools/ops/morning.sh
.PHONY: test-selected sim backtest edge finops region go-nogo verify-links

test-selected:
	python tools/ci/run_selected.py

sim:
	python -m src.sim.run_sim --config tests/fixtures/sim_config_sample.yaml --out artifacts/sim_sample.json

backtest:
	python -m tools.backtest.cli --config tests/fixtures/backtest_config_sample.yaml --out artifacts/backtest_sample.json

edge:
	python -m tools.edge_cli --trades tests/fixtures/edge_trades_case1.jsonl --quotes tests/fixtures/edge_quotes_case1.jsonl --out artifacts/EDGE_REPORT.json

finops:
	MM_FREEZE_UTC=1 python -m tools.finops.cron_job --artifacts tests/fixtures/artifacts_sample/metrics.json --exchange-dir tests/fixtures/exchange_reports --out-dir artifacts/finops_sample

region:
	MM_FREEZE_UTC=1 python -m tools.region.run_canary_compare --regions config/regions.yaml --in tests/fixtures/region_canary_metrics.jsonl --out artifacts/REGION_COMPARE.json

go-nogo:
	python -m tools.release.go_nogo

verify-links:
	python -m tools.release.verify_links

.PHONY: ready-bundle full-validate soak-14d all-ops

ready-bundle:
	python tools/ops/quick_cmds.py --do ready-bundle

full-validate:
	python tools/ops/quick_cmds.py --do full-validate

soak-14d:
	python tools/ops/quick_cmds.py --do soak-14d

all-ops:
	python tools/ops/quick_cmds.py --do all

.PHONY: ci-smoke ci-fix-json

ci-smoke:
	python -m tools.ci.smoke_tree --root .

ci-fix-json:
	python -m tools.ci.canon_json --mode=fix artifacts

.PHONY: test-circuit

test-circuit:
	python -m pytest -q -k circuit_gate_smoke

.PHONY: daily sentinel-dry

daily:
	python -m tools.ops.daily_check

sentinel-dry:
	python tools/ops/cron_sentinel.py --window-hours 24 --artifacts-dir artifacts --dry

.PHONY: full-accept

full-accept:
	python tools/ci/full_stack_validate.py --accept --artifacts-dir artifacts

.PHONY: nightly weekly kpi-gate

nightly:
	python -m tools.ops.cron_sentinel --window-hours 24 --artifacts-dir artifacts --dry
	python tools/ci/full_stack_validate.py --accept --artifacts-dir artifacts
	python -m tools.monitoring.validate_alerts
	python tools/ci/report_full_stack.py artifacts/FULL_STACK_VALIDATION.json

weekly:
	python -m tools.ops.cron_sentinel --window-hours 168 --artifacts-dir artifacts --dry
	python tools/ci/full_stack_validate.py --accept --artifacts-dir artifacts
	python -m tools.monitoring.validate_alerts
	python tools/ci/report_full_stack.py artifacts/FULL_STACK_VALIDATION.json

kpi-gate:
	$(MAKE) full-accept

.PHONY: ready-gate bundle bundle-auto release-dry release

ready-gate:
	python tools/release/ready_gate.py --kpi artifacts/KPI_GATE.json --min-readiness 85

bundle:
	python tools/release/make_ready.py && python tools/release/make_bundle.py

.PHONY: bundle-auto
PYTHON ?= python

bundle-auto:
	@echo "bundle-auto: running build/validation"
ifeq ($(VALIDATE),1)
	@$(PYTHON) tools/ci/full_stack_validate.py --accept --artifacts-dir artifacts
else
	@CI_FAST=1 $(PYTHON) tools/ci/full_stack_validate.py
endif
	@echo "bundle-auto: OK"

release-dry:
	@python scripts/release.py --version $(VER) --dry-run $(if $(VALIDATE),--validate,)

release:
	@python scripts/release.py --version $(VER)

.PHONY: soak-shadow soak-canary soak-live-econ

soak-shadow:
	python -m tools.ops.soak_orchestrator --phase shadow --hours 24 --full-accept --journal artifacts/SOAK_JOURNAL.jsonl --dry

soak-canary:
	python -m tools.ops.soak_orchestrator --phase canary --hours 24 --full-accept --journal artifacts/SOAK_JOURNAL.jsonl --dry

soak-live-econ:
	python -m tools.ops.soak_orchestrator --phase live-econ --hours 24 --full-accept --journal artifacts/SOAK_JOURNAL.jsonl --dry

.PHONY: archive-daily snapshot-on-fail

archive-daily:
	python -m tools.ops.artifacts_archive --src artifacts

snapshot-on-fail:
	python -m tools.ops.artifacts_snapshot_on_fail

.PHONY: soak-smoke
soak-smoke:
	@python -c "import os; os.makedirs('artifacts/soak_reports', exist_ok=True)"
	@python -m tools.ops.soak_run --shadow-hours 0.01 --canary-hours 0.01 --live-hours 0.02 --tz Europe/Berlin --out artifacts/soak_reports/smoke.json

.PHONY: soak
soak:
	@python -c "import os; os.makedirs('artifacts/soak_reports', exist_ok=True)"
	@python -c "import datetime; d=datetime.date.today().strftime('%%Y-%%m-%%d'); exec(open('temp_soak.py','w').write('print(\"artifacts/soak_reports/'+d+'.json\")'))" && python temp_soak.py > temp_path.txt && set /p OUT_PATH=<temp_path.txt && python -m tools.ops.soak_run --shadow-hours 6 --canary-hours 6 --live-hours 12 --tz Europe/Berlin --out %OUT_PATH% && del temp_path.txt temp_soak.py

.PHONY: soak-audit soak-audit-ci soak-compare soak-analyze

soak-audit:
	python -m tools.soak.audit_artifacts --base artifacts/soak/latest

soak-audit-ci:
	python -m tools.soak.audit_artifacts --base artifacts/soak/latest --fail-on-hold

soak-compare:
	python -m tools.soak.compare_runs --a artifacts/soak/run_A --b artifacts/soak/latest

soak-analyze:
	python -m tools.soak.analyze_post_soak --iter-glob "artifacts/soak/latest/ITER_SUMMARY_*.json" --min-windows 24 --exit-on-crit

soak-violations-redis:
	python -m tools.soak.export_violations_to_redis \
	  --summary reports/analysis/SOAK_SUMMARY.json \
	  --violations reports/analysis/VIOLATIONS.json \
	  --env dev --exchange bybit --redis-url redis://localhost:6379/0 --ttl 3600

soak-once:
	python -m tools.soak.continuous_runner \
	  --iter-glob "artifacts/soak/latest/ITER_SUMMARY_*.json" \
	  --min-windows 24 --max-iterations 1 --interval-min 0 \
	  --env $${ENV:-dev} --exchange $${EXCHANGE:-bybit} \
	  --redis-url $${REDIS_URL:-redis://localhost:6379/0} \
	  --ttl 3600 --stream --stream-maxlen 5000 --exit-on-crit --verbose

soak-continuous:
	python -m tools.soak.continuous_runner \
	  --iter-glob "artifacts/soak/latest/ITER_SUMMARY_*.json" \
	  --min-windows 24 --interval-min 60 --max-iterations 0 \
	  --env $${ENV:-dev} --exchange $${EXCHANGE:-bybit} \
	  --redis-url $${REDIS_URL:-redis://localhost:6379/0} \
	  --ttl 3600 --stream --stream-maxlen 5000 --verbose

soak-alert-dry:
	python -m tools.soak.continuous_runner \
	  --iter-glob "artifacts/soak/latest/ITER_SUMMARY_*.json" \
	  --min-windows 24 --max-iterations 1 \
	  --env $${ENV:-dev} --exchange $${EXCHANGE:-bybit} \
	  --redis-url $${REDIS_URL:-redis://localhost:6379/0} \
	  --ttl 1800 --stream --stream-maxlen 5000 \
	  --alert telegram --alert slack \
	  --alert-min-severity CRIT --alert-debounce-min 180 \
	  --heartbeat-key "soak:runner:heartbeat" \
	  --dry-run --verbose

soak-alert-selftest:
	@echo "=== Generating fake CRIT summary ==="
	python -m tools.soak.generate_fake_summary --crit --out reports/analysis
	@echo ""
	@echo "=== Creating fake ITER files ==="
	mkdir -p reports/analysis
	echo '{"window": 1}' > reports/analysis/FAKE_ITER_001.json
	@echo ""
	@echo "=== Running self-test (no debounce) ==="
	python -m tools.soak.continuous_runner \
	  --iter-glob "reports/analysis/FAKE_*.json" \
	  --min-windows 1 --max-iterations 1 \
	  --out-dir reports/analysis \
	  --env $${ENV:-dev} --exchange $${EXCHANGE:-bybit} \
	  --redis-url $${REDIS_URL:-redis://localhost:6379/0} \
	  --ttl 600 --stream --stream-maxlen 1000 \
	  --alert telegram --alert slack \
	  --alert-policy "$${ALERT_POLICY:-dev=WARN,staging=WARN,prod=CRIT}" \
	  --alert-debounce-min 0 \
	  --heartbeat-key "$${ENV:-dev}:$${EXCHANGE:-bybit}:soak:runner:selftest_heartbeat" \
	  --verbose || echo "[WARN] Self-test completed with warnings"

soak-qol-smoke:
	@echo "=== QoL Smoke Test (Debounce & Signature) ==="
	@echo "Step 1: Generate fake CRIT (variant 1)"
	python -m tools.soak.generate_fake_summary --crit --out reports/analysis --variant 1
	@echo ""
	@echo "Step 2: First run (should alert)"
	python -m tools.soak.continuous_runner \
	  --iter-glob "reports/analysis/FAKE_*.json" \
	  --min-windows 1 --max-iterations 1 \
	  --env $${ENV:-dev} --exchange $${EXCHANGE:-bybit} \
	  --redis-url $${REDIS_URL:-redis://localhost:6379/0} \
	  --ttl 600 --stream --stream-maxlen 1000 \
	  --alert telegram --alert slack \
	  --alert-policy "$${ALERT_POLICY:-dev=WARN,prod=CRIT}" \
	  --alert-debounce-min 180 \
	  --redis-down-max 3 \
	  --heartbeat-key "$${ENV:-dev}:$${EXCHANGE:-bybit}:soak:runner:heartbeat" \
	  --verbose
	@echo ""
	@echo "Step 3: Second run (should DEBOUNCE - same violations)"
	python -m tools.soak.continuous_runner \
	  --iter-glob "reports/analysis/FAKE_*.json" \
	  --min-windows 1 --max-iterations 1 \
	  --env $${ENV:-dev} --exchange $${EXCHANGE:-bybit} \
	  --redis-url $${REDIS_URL:-redis://localhost:6379/0} \
	  --ttl 600 --stream --stream-maxlen 1000 \
	  --alert telegram --alert slack \
	  --alert-policy "$${ALERT_POLICY:-dev=WARN,prod=CRIT}" \
	  --alert-debounce-min 180 \
	  --redis-down-max 3 \
	  --heartbeat-key "$${ENV:-dev}:$${EXCHANGE:-bybit}:soak:runner:heartbeat" \
	  --verbose

soak-qol-smoke-new-viol:
	@echo "=== QoL Smoke Test (New Violations Signature) ==="
	@echo "Step 1: Generate different CRIT (variant 2 - new signature)"
	python -m tools.soak.generate_fake_summary --crit --out reports/analysis --variant 2
	@echo ""
	@echo "Step 2: Run again (should BYPASS debounce - signature_changed=true)"
	python -m tools.soak.continuous_runner \
	  --iter-glob "reports/analysis/FAKE_*.json" \
	  --min-windows 1 --max-iterations 1 \
	  --env $${ENV:-dev} --exchange $${EXCHANGE:-bybit} \
	  --redis-url $${REDIS_URL:-redis://localhost:6379/0} \
	  --ttl 600 --stream --stream-maxlen 1000 \
	  --alert telegram --alert slack \
	  --alert-policy "$${ALERT_POLICY:-dev=WARN,prod=CRIT}" \
	  --alert-debounce-min 180 \
	  --redis-down-max 3 \
	  --heartbeat-key "$${ENV:-dev}:$${EXCHANGE:-bybit}:soak:runner:heartbeat" \
	  --verbose

.PHONY: shadow-run shadow-audit shadow-ci shadow-report shadow-redis shadow-redis-export shadow-redis-export-prod shadow-redis-export-dry shadow-redis-export-legacy shadow-archive soak-analyze soak-violations-redis soak-once soak-continuous soak-alert-dry soak-alert-selftest soak-qol-smoke soak-qol-smoke-new-viol accuracy-compare accuracy-ci

shadow-run:
	python -m tools.shadow.run_shadow --iterations 6 --duration 60 --source mock

shadow-redis:
	python -m tools.shadow.run_shadow \
	  --source redis \
	  --redis-url redis://localhost:6379 \
	  --redis-stream lob:ticks \
	  --redis-group shadow \
	  --symbols BTCUSDT ETHUSDT \
	  --profile moderate \
	  --iterations 48 \
	  --duration 60 \
	  --touch_dwell_ms 25 \
	  --require_volume \
	  --min_lot 0.001 && \
	python -m tools.shadow.build_shadow_reports --src artifacts/shadow/latest && \
	python -m tools.shadow.audit_shadow_artifacts --base artifacts/shadow/latest --min_windows 48

shadow-audit:
	python -m tools.shadow.audit_shadow_artifacts --base artifacts/shadow/latest --min_windows 48

shadow-ci:
	python -m tools.shadow.audit_shadow_artifacts --base artifacts/shadow/latest --min_windows 48 --fail-on-hold

shadow-report:
	python -m tools.shadow.build_shadow_reports --src artifacts/shadow/latest && \
	python -m tools.shadow.audit_shadow_artifacts --base artifacts/shadow/latest --min_windows 48

shadow-archive:
	python -m tools.ops.rotate_shadow_artifacts --max-keep 300

shadow-redis-export:
	python -m tools.shadow.export_to_redis --src artifacts/soak/latest --redis-url redis://localhost:6379/0 --env dev --exchange bybit --hash-mode --batch-size 50 --ttl 3600 --show-metrics

shadow-redis-export-prod:
	python -m tools.shadow.export_to_redis --src artifacts/soak/latest --redis-url rediss://prod.redis.com:6380/0 --env prod --exchange bybit --hash-mode --batch-size 100 --ttl 7200 --show-metrics

shadow-redis-export-dry:
	python -m tools.shadow.export_to_redis --src artifacts/soak/latest --redis-url redis://localhost:6379/0 --env dev --exchange bybit --hash-mode --dry-run --show-metrics

shadow-redis-export-legacy:
	python -m tools.shadow.export_to_redis --src artifacts/soak/latest --redis-url redis://localhost:6379/0 --env dev --exchange bybit --flat-keys --batch-size 50 --ttl 3600

.PHONY: redis-smoke redis-smoke-prod redis-smoke-flat

redis-smoke:
	python -m tools.shadow.redis_smoke_check --src artifacts/soak/latest --env dev --exchange bybit --batch-size 100 --sample-keys 10 --redis-url redis://localhost:6379/0

redis-smoke-prod:
	python -m tools.shadow.redis_smoke_check --src artifacts/soak/latest --env prod --exchange bybit --batch-size 100 --sample-keys 10 --redis-url rediss://user:pass@redis.prod:6379/0

redis-smoke-flat:
	python -m tools.shadow.redis_smoke_check --src artifacts/soak/latest --env dev --exchange bybit --batch-size 100 --sample-keys 10 --do-flat-backfill --redis-url redis://localhost:6379/0

.PHONY: dryrun dryrun-validate

dryrun:
	python -m tools.dryrun.run_dryrun --symbols BTCUSDT ETHUSDT --iterations 6 --duration 60

dryrun-validate:
	python -m tools.dryrun.run_dryrun --symbols BTCUSDT ETHUSDT --iterations 12 --duration 60

.PHONY: accuracy-compare accuracy-ci

accuracy-compare:
	@echo "=== Accuracy Gate: Shadow ↔ Dry-Run Comparison ==="
	python -m tools.accuracy.compare_shadow_dryrun \
	  --shadow "artifacts/shadow/latest/ITER_SUMMARY_*.json" \
	  --dryrun "artifacts/dryrun/latest/ITER_SUMMARY_*.json" \
	  --symbols $${SYMBOLS:-BTCUSDT,ETHUSDT} \
	  --min-windows $${MIN_WINDOWS:-24} \
	  --max-age-min $${MAX_AGE_MIN:-90} \
	  --mape-threshold $${MAPE_THRESHOLD:-0.15} \
	  --median-delta-threshold-bps $${MEDIAN_DELTA_THRESHOLD_BPS:-1.5} \
	  --out-dir reports/analysis \
	  --verbose

accuracy-ci:
	@echo "=== Accuracy Gate: CI Mode (strict) ==="
	python -m tools.accuracy.compare_shadow_dryrun \
	  --shadow "artifacts/shadow/latest/ITER_SUMMARY_*.json" \
	  --dryrun "artifacts/dryrun/latest/ITER_SUMMARY_*.json" \
	  --symbols BTCUSDT,ETHUSDT \
	  --min-windows 24 \
	  --max-age-min 90 \
	  --mape-threshold 0.15 \
	  --median-delta-threshold-bps 1.5 \
	  --out-dir reports/analysis \
	  --verbose
	@echo ""
	@if [ -f reports/analysis/ACCURACY_SUMMARY.json ]; then \
		VERDICT=$$(jq -r '.verdict' reports/analysis/ACCURACY_SUMMARY.json); \
		echo "Verdict: $$VERDICT"; \
		if [ "$$VERDICT" = "FAIL" ]; then \
			echo "❌ Accuracy Gate FAILED - blocking PR"; \
			exit 1; \
		elif [ "$$VERDICT" = "WARN" ]; then \
			echo "🟡 Accuracy Gate WARN - informational"; \
			exit 0; \
		else \
			echo "✅ Accuracy Gate PASSED"; \
			exit 0; \
		fi; \
	else \
		echo "❌ ACCURACY_SUMMARY.json not found"; \
		exit 1; \
	fi

.PHONY: pre-freeze pre-freeze-alt pre-freeze-fast

pre-freeze:
	python -m tools.release.pre_freeze_sanity --src "artifacts/soak/latest" --smoke-iters 6 --post-iters 8 --run-isolated

pre-freeze-alt:
	python -m tools.release.pre_freeze_sanity --src "artifacts/soak/latest 1" --smoke-iters 6 --post-iters 8 --run-isolated

pre-freeze-fast:
	python -m tools.release.pre_freeze_sanity --src "artifacts/soak/latest" --smoke-iters 3 --post-iters 4