from pathlib import Path

from tools.finops.exporter import load_artifacts, export_pnl_csv, export_fees_csv, export_turnover_csv, export_latency_csv, export_edge_csv


def test_finops_exports(tmp_path):
    root = Path(__file__).resolve().parents[1]
    art = load_artifacts(str(root / "fixtures" / "artifacts_sample" / "metrics.json"))
    out = tmp_path / "finops"
    out.mkdir(parents=True, exist_ok=True)
    export_pnl_csv(art, str(out / "pnl.csv"))
    export_fees_csv(art, str(out / "fees.csv"))
    export_turnover_csv(art, str(out / "turnover.csv"))
    export_latency_csv(art, str(out / "latency.csv"))
    export_edge_csv(art, str(out / "edge.csv"))

    # Verify all CSV files were created and have valid structure
    for name in ("pnl.csv","fees.csv","turnover.csv","latency.csv","edge.csv"):
        csv_file = out / name
        assert csv_file.exists(), f"{name} not created"
        content = csv_file.read_text(encoding='ascii').replace('\r\n', '\n')
        assert content.endswith("\n"), f"{name} should end with newline"
        lines = content.strip().split('\n')
        assert len(lines) >= 1, f"{name} should have at least header"
        # Verify header exists and has columns
        assert ',' in lines[0], f"{name} header should have comma-separated columns"


