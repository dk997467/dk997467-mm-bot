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

    gdir = root / "golden" / "finops_exports"
    for name in ("pnl.csv","fees.csv","turnover.csv","latency.csv","edge.csv"):
        got = (out / name).read_bytes()
        exp = (gdir / name).read_bytes()
        assert got.endswith(b"\n")
        assert got == exp


