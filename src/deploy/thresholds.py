"""
F1 deployment gate thresholds configuration.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Tuple, Any, List
from copy import deepcopy
import json
import threading


@dataclass
class GateThresholds:
    """F1 deployment gate thresholds with production defaults."""
    
    # Walk-forward tuning gates (D2)
    min_hit_rate: float = 0.01
    min_maker_share: float = 0.90
    min_net_pnl_usd: float = 0.0
    max_cvar95_loss_usd: float = 10.0
    min_splits_win_ratio: float = 0.60
    max_param_drift_pct: float = 50.0
    
    # E2 calibration gates  
    max_sim_live_divergence: float = 0.15
    
    # Report freshness
    max_report_age_hours: float = 72
    
    # F2 gate — Throttle
    max_throttle_backoff_ms: float = 5000.0
    max_throttle_events_in_window_total: int = 50
    
    # F2 gate — Autopolicy
    max_autopolicy_level_on_promote: int = 1
    autopolicy_soft_canary_shrink_pct: float = 0.25
    autopolicy_soft_tib_bump_pct: float = 0.15
    autopolicy_soft_repbps_bump_pct: float = 0.15

    # F2 gate — Canary signals (defaults)
    canary_max_reject_delta: float = 0.02
    canary_max_latency_delta_ms: int = 50
    canary_min_sample_fills: int = 500

    # F2 gate — Circuit
    circuit_window_sec: int = 300
    circuit_max_err_rate_ratio: float = 0.15
    circuit_min_closed_sec: int = 180
    circuit_half_open_probe: int = 5

    # Phase caps (order share, capital, taker ceiling)
    phase_shadow_order_share_ratio: float = 0.00
    phase_canary_order_share_ratio: float = 0.05
    phase_live_econ_order_share_ratio: float = 0.15
    phase_canary_capital_usd: int = 500
    phase_live_econ_capital_usd: int = 2000
    phase_taker_ceiling_ratio: float = 0.15

# Global and per-symbol throttle thresholds for F2 audit
THROTTLE_GLOBAL: Dict[str, int] = {
    "max_throttle_backoff_ms": 2000,
    "max_throttle_events_in_window_total": 100,
}

THROTTLE_PER_SYMBOL: Dict[str, Dict[str, int]] = {}

# Strict validation mode for overrides
STRICT_THRESHOLDS: bool = False

# Private lock and versioning for atomic updates
_thr_lock = threading.RLock()
_THRESHOLDS_VERSION: int = 0

# Canonical stores (public dicts are canonical; updates happen in-place under lock)
_THROTTLE_GLOBAL = THROTTLE_GLOBAL
_THROTTLE_PER_SYMBOL = THROTTLE_PER_SYMBOL

# Canary gate thresholds (hot-reloadable maps)
CANARY_GATE: Dict[str, int | float] = {
    "max_reject_delta": 0.02,
    "max_latency_delta_ms": 50,
    "min_sample_fills": 500,
    "drift_cap_pct": 5.0,
    "tail_min_sample": 200,
    "tail_p95_cap_ms": 50,
    "tail_p99_cap_ms": 100,
    "slo_tail_min_sample": 200,
    "slo_tail_p95_cap_ms": 50,
    "slo_tail_p99_cap_ms": 100,
    # M1.1 — Markout gate thresholds
    "markout_min_sample": 50,
    "markout_cap_bps_200": 0.5,
    "markout_cap_bps_500": 0.5,
}
CANARY_GATE_PER_SYMBOL: Dict[str, Dict[str, int | float]] = {}

# Phase limits store (hot-reloadable in future)
PHASE_CAPS: Dict[str, Dict[str, float | int]] = {
    "shadow": {
        "order_share_ratio": 0.00,
        "capital_usd": 0,
        "taker_ceiling_ratio": 0.15,
    },
    "canary": {
        "order_share_ratio": 0.05,
        "capital_usd": 500,
        "taker_ceiling_ratio": 0.15,
    },
    "live-econ": {
        "order_share_ratio": 0.15,
        "capital_usd": 2000,
        "taker_ceiling_ratio": 0.15,
    },
}


def _norm_symbol(s: Optional[str]) -> str:
    return (s or "").strip().upper()


def _find_override_for_symbol(symbol: str) -> Tuple[str, Dict[str, int]]:
    """Find per-symbol override by normalized key (case-insensitive)."""
    norm = _norm_symbol(symbol)
    # Take snapshot under lock to avoid races while scanning
    with _thr_lock:
        per = dict(_THROTTLE_PER_SYMBOL)
    # Direct hits
    if norm in per:
        return norm, per[norm] or {}
    if symbol in per:
        return symbol, per[symbol] or {}
    low = symbol.lower()
    if low in per:
        return low, per[low] or {}
    # Scan for any key that normalizes to norm
    for k, v in per.items():
        try:
            if _norm_symbol(k) == norm:
                return k, v or {}
        except Exception:
            continue
    return "", {}


def get_throttle_thresholds(symbol: str) -> Dict[str, int]:
    """Return merged throttle thresholds for a symbol.

    - Start with THROTTLE_GLOBAL
    - Apply overrides from THROTTLE_PER_SYMBOL[symbol] (case-insensitive)
    - Validate override values are int and >=0
    - On invalid override: raise if STRICT_THRESHOLDS else warn+fallback to global
    """
    with _thr_lock:
        base = deepcopy(_THROTTLE_GLOBAL)
        _k, override = _find_override_for_symbol(str(symbol))
    if override:
        try:
            merged = deepcopy(base)
            for k, v in override.items():
                if not isinstance(v, int) or v < 0:
                    raise ValueError(f"invalid_override {symbol} {k} {v}")
                merged[k] = v
            return merged
        except ValueError:
            if STRICT_THRESHOLDS:
                raise
            # ascii-only warning
            print(f"WARN invalid_throttle_override symbol={_norm_symbol(symbol)} key={k} value={v}")
            return base
    return base


def get_canary_gate_thresholds(symbol: str | None = None) -> Dict[str, int | float]:
    """Return current canary gate thresholds, optionally merged for symbol."""
    with _thr_lock:
        base: Dict[str, int | float] = {
            "max_reject_delta": float(CANARY_GATE.get("max_reject_delta", 0.02)),
            "max_latency_delta_ms": int(CANARY_GATE.get("max_latency_delta_ms", 50)),
            "min_sample_fills": int(CANARY_GATE.get("min_sample_fills", 500)),
            "drift_cap_pct": float(CANARY_GATE.get("drift_cap_pct", 5.0)),
            "tail_min_sample": int(CANARY_GATE.get("tail_min_sample", 200)),
            "tail_p95_cap_ms": int(CANARY_GATE.get("tail_p95_cap_ms", 50)),
            "tail_p99_cap_ms": int(CANARY_GATE.get("tail_p99_cap_ms", 100)),
            "slo_tail_min_sample": int(CANARY_GATE.get("slo_tail_p95_cap_ms", 200)),
            "slo_tail_p95_cap_ms": int(CANARY_GATE.get("slo_tail_p95_cap_ms", 50)),
            "slo_tail_p99_cap_ms": int(CANARY_GATE.get("slo_tail_p99_cap_ms", 100)),
            # M1.1 — Markout gate thresholds
            "markout_min_sample": int(CANARY_GATE.get("markout_min_sample", 50)),
            "markout_cap_bps_200": float(CANARY_GATE.get("markout_cap_bps_200", 0.5)),
            "markout_cap_bps_500": float(CANARY_GATE.get("markout_cap_bps_500", 0.5)),
        }
        if not symbol:
            return base
        sym = _norm_symbol(symbol)
        over = CANARY_GATE_PER_SYMBOL.get(sym) or CANARY_GATE_PER_SYMBOL.get(symbol) or {}
        try:
            merged = dict(base)
            if isinstance(over, dict):
                for k, v in over.items():
                    if k in ("max_latency_delta_ms", "min_sample_fills", "tail_min_sample", "tail_p95_cap_ms", "tail_p99_cap_ms", "slo_tail_min_sample", "slo_tail_p95_cap_ms", "slo_tail_p99_cap_ms", "markout_min_sample"):
                        iv = int(v)
                        if iv < 0:
                            raise ValueError
                        merged[k] = iv
                    elif k in ("max_reject_delta", "drift_cap_pct", "markout_cap_bps_200", "markout_cap_bps_500"):
                        fv = float(v)
                        if fv < 0:
                            raise ValueError
                        merged[k] = fv
                    else:
                        continue
            return merged
        except Exception:
            if STRICT_THRESHOLDS:
                raise ValueError(f"invalid_canary_override {symbol}")
            print(f"WARN invalid_canary_override symbol={sym}")
            return base


def _normalize_yaml_ascii(s: str) -> str:
    """Normalize YAML content for robust parsing.
    
    - ASCII validation: raise ValueError if any char > 0x7f
    - Normalize line endings: \r\n -> \n
    - Remove BOM
    - Trim trailing spaces at end of lines
    - Remove empty lines and comment lines starting with #
    - Remove common left indentation
    """
    # ASCII guard
    if any(ord(ch) > 0x7f for ch in s):
        raise ValueError("non_ascii")
    
    # Normalize line endings
    s = s.replace('\r\n', '\n')
    
    # Remove BOM
    if s.startswith('\ufeff'):
        s = s[1:]
    
    lines = s.splitlines()
    
    # Remove empty lines and comment lines, trim trailing spaces
    filtered_lines = []
    for line in lines:
        stripped = line.rstrip()
        if stripped and not stripped.lstrip().startswith('#'):
            # Remove inline comments (everything after #)
            if '#' in stripped:
                stripped = stripped.split('#')[0].rstrip()
            if stripped:  # Check again after removing comment
                filtered_lines.append(stripped)
    
    if not filtered_lines:
        return ""
    
    # Find minimum leading whitespace among non-empty lines
    min_indent = min(len(line) - len(line.lstrip()) for line in filtered_lines)
    
    # Remove common left indentation
    normalized_lines = []
    for line in filtered_lines:
        if len(line) >= min_indent:
            normalized_lines.append(line[min_indent:])
        else:
            normalized_lines.append(line)
    
    return '\n'.join(normalized_lines)


def _yaml_like_parse(path: str) -> Dict[str, Any]:
    """Parse a very small YAML subset sufficient for thresholds file.

    Supports mappings with indentation and scalar ints/strings.
    Ignores comments and empty lines.
    """
    with open(path, 'r', encoding='utf-8', errors='strict') as f:
        content = f.read()
    
    # Normalize YAML content for robust parsing
    content = _normalize_yaml_ascii(content)
    
    # ASCII-only enforcement for safety (deterministic parsing)
    if any(ord(ch) > 127 for ch in content):
        raise ValueError("non_ascii")
    if not content or all(ch.isspace() for ch in content):
        raise ValueError("empty_yaml")
    
    lines = content.splitlines()
    root: Dict[str, Any] = {}
    # Stack of (indent_level, current_dict)
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    
    for raw in lines:
        if not raw or raw.strip() == '' or raw.lstrip().startswith('#'):
            continue
        # count leading spaces
        indent = len(raw) - len(raw.lstrip(' '))
        line = raw.strip()
        # key: or key: value
        if ':' not in line:
            # invalid, keep tolerant: skip
            continue
        key, sep, value = line.partition(':')
        key = key.strip()
        value = value.strip()
        
        # adjust stack to current indent
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value == '':
            # start new dict
            node: Dict[str, Any] = {}
            parent[key] = node
            stack.append((indent, node))
        else:
            # scalar value -> try int
            v: Any
            if value.lower() in ('true', 'false'):
                v = True if value.lower() == 'true' else False
            else:
                # try int, then float, fallback to string
                try:
                    v = int(value)
                except Exception:
                    try:
                        v = float(value)
                    except Exception:
                        v = value
            parent[key] = v
    
    return root


def load_thresholds_from_yaml(path: str) -> Dict[str, Any]:
    """Load throttle thresholds from YAML-like file.

    Returns structured dict with keys: 'throttle' → { 'global': {...}, 'per_symbol': {...} }
    Unknown keys are preserved and ignored by refresh.
    """
    try:
        data = _yaml_like_parse(path)
        if not isinstance(data, dict):
            raise ValueError("invalid_yaml_structure")
        # Require at least one recognized top-level key
        recognized = {'throttle', 'canary_gate', 'canary_gate_per_symbol'}
        if not any(k in data for k in recognized):
            raise ValueError("invalid_yaml_no_keys")
        return data
    except Exception as e:
        raise ValueError(f"failed_to_parse_yaml {e}")


def refresh_thresholds(path: str) -> Dict[str, Any]:
    """Reload thresholds from YAML and apply into globals.

    Returns deterministic summary dict including throttle and canary sections.
    """
    try:
        data = load_thresholds_from_yaml(path)
        th = data.get('throttle', {}) if isinstance(data, dict) else {}
        g = th.get('global', {}) if isinstance(th, dict) else {}
        ps = th.get('per_symbol', {}) if isinstance(th, dict) else {}
        cg = data.get('canary_gate', {}) if isinstance(data, dict) else {}
        cgps = data.get('canary_gate_per_symbol', {}) if isinstance(data, dict) else {}

        # Build new maps
        new_global: Dict[str, int] = {}
        for k, v in (g.items() if isinstance(g, dict) else []):
            try:
                iv = int(v)
                if iv < 0:
                    raise ValueError
                new_global[str(k)] = iv
            except Exception:
                # ignore invalid entries
                print(f"WARN invalid_global key={k} value={v}")
                continue

        new_per: Dict[str, Dict[str, int]] = {}
        if isinstance(ps, dict):
            for sym, overrides in ps.items():
                if not isinstance(overrides, dict):
                    continue
                symn = _norm_symbol(str(sym))
                od: Dict[str, int] = {}
                for k, v in overrides.items():
                    try:
                        iv = int(v)
                        if iv < 0:
                            raise ValueError
                        od[str(k)] = iv
                    except Exception:
                        print(f"WARN invalid_symbol_override symbol={symn} key={k} value={v}")
                        # skip invalid key
                        continue
                new_per[symn] = od

        # Apply atomically (copy-on-write via in-place swap under lock)
        with _thr_lock:
            THROTTLE_GLOBAL.clear()
            THROTTLE_GLOBAL.update(new_global or THROTTLE_GLOBAL)
            THROTTLE_PER_SYMBOL.clear()
            THROTTLE_PER_SYMBOL.update(new_per)
            # Apply canary gate (global)
            if isinstance(cg, dict):
                try:
                    if 'max_reject_delta' in cg:
                        CANARY_GATE['max_reject_delta'] = float(cg.get('max_reject_delta'))
                    if 'max_latency_delta_ms' in cg:
                        CANARY_GATE['max_latency_delta_ms'] = int(cg.get('max_latency_delta_ms'))
                    if 'min_sample_fills' in cg:
                        CANARY_GATE['min_sample_fills'] = int(cg.get('min_sample_fills'))
                    if 'drift_cap_pct' in cg:
                        CANARY_GATE['drift_cap_pct'] = float(cg.get('drift_cap_pct'))
                    if 'tail_min_sample' in cg:
                        CANARY_GATE['tail_min_sample'] = int(cg.get('tail_min_sample'))
                    if 'tail_p95_cap_ms' in cg:
                        CANARY_GATE['tail_p95_cap_ms'] = int(cg.get('tail_p95_cap_ms'))
                    if 'tail_p99_cap_ms' in cg:
                        CANARY_GATE['tail_p99_cap_ms'] = int(cg.get('tail_p99_cap_ms'))
                    # M1.1 — Markout gate thresholds
                    if 'markout_min_sample' in cg:
                        CANARY_GATE['markout_min_sample'] = int(cg.get('markout_min_sample'))
                    if 'markout_cap_bps_200' in cg:
                        CANARY_GATE['markout_cap_bps_200'] = float(cg.get('markout_cap_bps_200'))
                    if 'markout_cap_bps_500' in cg:
                        CANARY_GATE['markout_cap_bps_500'] = float(cg.get('markout_cap_bps_500'))
                except Exception:
                    # ignore invalid cg values
                    pass
            # Apply canary per-symbol overrides
            try:
                new_cgps: Dict[str, Dict[str, int | float]] = {}
                if isinstance(cgps, dict):
                    for sym, ov in cgps.items():
                        if not isinstance(ov, dict):
                            continue
                        symn = _norm_symbol(str(sym))
                        merged: Dict[str, int | float] = {}
                        for k, v in ov.items():
                            try:
                                if k in ('max_latency_delta_ms', 'min_sample_fills', 'tail_min_sample', 'tail_p95_cap_ms', 'tail_p99_cap_ms', 'slo_tail_min_sample', 'slo_tail_p95_cap_ms', 'slo_tail_p99_cap_ms', 'markout_min_sample'):
                                    iv = int(v)
                                    if iv < 0:
                                        raise ValueError
                                    merged[k] = iv
                                elif k in ('max_reject_delta', 'drift_cap_pct', 'markout_cap_bps_200', 'markout_cap_bps_500'):
                                    fv = float(v)
                                    if fv < 0:
                                        raise ValueError
                                    merged[k] = fv
                                else:
                                    continue
                            except Exception:
                                if STRICT_THRESHOLDS:
                                    raise ValueError(f"invalid_canary_symbol_override {symn} {k} {v}")
                                print(f"WARN invalid_canary_symbol_override symbol={symn} key={k} value={v}")
                                continue
                        new_cgps[symn] = merged
                CANARY_GATE_PER_SYMBOL.clear()
                CANARY_GATE_PER_SYMBOL.update(new_cgps)
            except ValueError:
                raise
            except Exception:
                pass
            global _THRESHOLDS_VERSION
            _THRESHOLDS_VERSION += 1
            version_now = _THRESHOLDS_VERSION

        symbols = sorted(list(new_per.keys()))
        # include canary maps in summary
        with _thr_lock:
            cgpss = {k: dict(v) for k, v in CANARY_GATE_PER_SYMBOL.items()}
        summary = {
            "global_keys": int(len(new_global)),
            "per_symbol_count": int(len(new_per)),
            "symbols": symbols,
            "version": int(version_now),
            "canary_gate": get_canary_gate_thresholds(),
            "canary_gate_per_symbol": cgpss,
        }
        # deterministic ascii log
        print(json.dumps({"event": "thresholds_reloaded", **summary}, sort_keys=True, separators=(",", ":")))
        # metrics (stdlib counters)
        try:
            from src.metrics import exporter as mexp
            mexp.inc_thresholds_reload(True)
            mexp.set_thresholds_version(version_now)
        except Exception:
            pass
        return summary
    except Exception as e:
        # deterministic ascii log
        print(json.dumps({"event": "thresholds_reload_failed", "error": str(e)}, sort_keys=True, separators=(",", ":")))
        try:
            from src.metrics import exporter as mexp
            mexp.inc_thresholds_reload(False)
        except Exception:
            pass
        raise


def current_thresholds_snapshot() -> Dict[str, Any]:
    """Return current thresholds snapshot for admin/smoke tests."""
    with _thr_lock:
        ver = int(_THRESHOLDS_VERSION)
        g = {k: int(v) for k, v in THROTTLE_GLOBAL.items()}
        per = { _norm_symbol(k): {kk: int(vv) for kk, vv in (vvv.items() if isinstance(vvv, dict) else {})} for k, vvv in THROTTLE_PER_SYMBOL.items() }
        cgpss = {k: dict(v) for k, v in CANARY_GATE_PER_SYMBOL.items()}
    # Return deterministic ordering by sorting keys when dumped
    cg = get_canary_gate_thresholds()
    with _thr_lock:
        phase_caps = {k: dict(v) for k, v in PHASE_CAPS.items()}
    return {"version": ver, "global": g, "per_symbol": per, "canary_gate": cg, "canary_gate_per_symbol": cgpss, "phase_caps": phase_caps}


def get_thresholds_version() -> int:
    with _thr_lock:
        return int(_THRESHOLDS_VERSION)


def get_phase_caps(phase: str) -> Dict[str, float | int]:
    """Return phase caps dict for phase in {shadow, canary, live-econ}.

    Keys: order_share_ratio (float), capital_usd (int), taker_ceiling_ratio (float)
    """
    key = str(phase).strip()
    with _thr_lock:
        caps = PHASE_CAPS.get(key) or PHASE_CAPS.get(key.lower()) or PHASE_CAPS.get(key.upper())
        if not caps:
            caps = PHASE_CAPS.get("shadow", {})
        return dict(caps)


def load_thresholds(path: Optional[str] = None) -> GateThresholds:
    """Load thresholds from YAML/JSON file or return defaults."""
    if path is None:
        return GateThresholds()
    
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Thresholds file not found: {path}")
    
    try:
        # Try YAML first (optional dependency)
        try:
            import yaml
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
        except ImportError:
            # Fallback to JSON
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
        
        # Create GateThresholds with loaded values
        return GateThresholds(**config_data)
        
    except Exception as e:
        raise ValueError(f"Failed to load thresholds from {path}: {e}")


def validate_thresholds(thresholds: GateThresholds) -> list[str]:
    """Validate threshold values and return list of errors."""
    errors = []
    
    # Validate ranges
    if not (0.0 <= thresholds.min_hit_rate <= 1.0):
        errors.append(f"min_hit_rate must be in [0,1], got {thresholds.min_hit_rate}")
    
    if not (0.0 <= thresholds.min_maker_share <= 1.0):
        errors.append(f"min_maker_share must be in [0,1], got {thresholds.min_maker_share}")
    
    if thresholds.max_cvar95_loss_usd < 0:
        errors.append(f"max_cvar95_loss_usd must be >= 0, got {thresholds.max_cvar95_loss_usd}")
    
    if not (0.0 <= thresholds.min_splits_win_ratio <= 1.0):
        errors.append(f"min_splits_win_ratio must be in [0,1], got {thresholds.min_splits_win_ratio}")
    
    if thresholds.max_param_drift_pct <= 0:
        errors.append(f"max_param_drift_pct must be > 0, got {thresholds.max_param_drift_pct}")
    
    if not (0.0 <= thresholds.max_sim_live_divergence <= 1.0):
        errors.append(f"max_sim_live_divergence must be in [0,1], got {thresholds.max_sim_live_divergence}")
    
    if thresholds.max_report_age_hours <= 0:
        errors.append(f"max_report_age_hours must be > 0, got {thresholds.max_report_age_hours}")
    
    return errors


def save_thresholds_example(output_path: str = "src/deploy/thresholds.example.yaml") -> None:
    """Save example thresholds file."""
    defaults = GateThresholds()
    
    yaml_content = f"""# F1 Deployment Gate Thresholds
# 
# Walk-forward tuning gates (D2)
min_hit_rate: {defaults.min_hit_rate}
min_maker_share: {defaults.min_maker_share}
min_net_pnl_usd: {defaults.min_net_pnl_usd}
max_cvar95_loss_usd: {defaults.max_cvar95_loss_usd}
min_splits_win_ratio: {defaults.min_splits_win_ratio}
max_param_drift_pct: {defaults.max_param_drift_pct}

# E2 calibration gates
max_sim_live_divergence: {defaults.max_sim_live_divergence}

# Report freshness
max_report_age_hours: {defaults.max_report_age_hours}
"""
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(yaml_content)


if __name__ == "__main__":
    # Generate example file
    save_thresholds_example()
    print("Generated src/deploy/thresholds.example.yaml")
    
    # Test loading defaults
    defaults = GateThresholds()
    print(f"Default max_sim_live_divergence: {defaults.max_sim_live_divergence}")
    
    # Validate defaults
    errors = validate_thresholds(defaults)
    if errors:
        print(f"Validation errors: {errors}")
    else:
        print("Default thresholds are valid")
