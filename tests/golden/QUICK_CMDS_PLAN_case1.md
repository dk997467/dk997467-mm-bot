QUICK CMDS PLAN
RUN python tools/release/make_ready.py
RUN python tools/release/make_bundle.py
RUN python tools/ci/full_stack_validate.py
RUN python tools/ci/report_full_stack.py artifacts/FULL_STACK_VALIDATION.json
RUN python tools/soak/long_run.py --weeks 2 --hours-per-night 8 --econ yes
QUICK_CMDS=PLAN


