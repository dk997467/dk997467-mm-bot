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

.PHONY: pre-freeze pre-freeze-alt pre-freeze-fast

pre-freeze:
	python -m tools.release.pre_freeze_sanity --src "artifacts/soak/latest" --smoke-iters 6 --post-iters 8 --run-isolated

pre-freeze-alt:
	python -m tools.release.pre_freeze_sanity --src "artifacts/soak/latest 1" --smoke-iters 6 --post-iters 8 --run-isolated

pre-freeze-fast:
	python -m tools.release.pre_freeze_sanity --src "artifacts/soak/latest" --smoke-iters 3 --post-iters 4