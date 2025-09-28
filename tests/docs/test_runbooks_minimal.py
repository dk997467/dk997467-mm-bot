from pathlib import Path


def test_runbooks_have_h1():
    for rel in ('docs/runbooks/circuit_gate.md','docs/runbooks/full_stack.md','docs/runbooks/kpi.md'):
        s = Path(rel).read_text(encoding='utf-8')
        assert s.lstrip().startswith('# ')

