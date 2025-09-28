import json
import os
from typing import Any, Dict, List, Tuple

import yaml


_ALLOWED_PREFIXES: Tuple[Tuple[str, ...], ...] = (
    ('allocator', 'smoothing'),
    ('signals',),
    ('latency_boost', 'replace'),
    ('latency_boost', 'tail_batch'),
    ('canary',),
    ('logging',),
)


def _load_profiles(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='ascii') as f:
        d = yaml.safe_load(f) or {}
    return d.get('profiles', {})


def _is_allowed_path(path: List[str]) -> bool:
    t = tuple(path)
    for prefix in _ALLOWED_PREFIXES:
        if t[:len(prefix)] == prefix:
            return True
    return False


def _deep_merge_allowed(base: Dict[str, Any], overlay: Dict[str, Any], path: List[str] = None) -> Dict[str, Any]:
    if path is None:
        path = []
    result = dict(base)
    for k, v in overlay.items():
        pk = path + [str(k)]
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            if _is_allowed_path(pk):
                result[k] = _deep_merge_allowed(base.get(k, {}), v, pk)
            else:
                # Recurse but only include allowed grandchildren
                filtered_child = _deep_merge_allowed(base.get(k, {}) if isinstance(base.get(k), dict) else {}, v, pk)
                if filtered_child != (base.get(k) or {}):
                    result[k] = filtered_child
        else:
            if _is_allowed_path(pk):
                result[k] = v
    return result


def apply_profile(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    profiles = _load_profiles('config/profiles.yaml')
    prof = profiles.get(name, {})
    if not prof:
        return dict(cfg)
    before = cfg
    after = _deep_merge_allowed(before, prof)
    # ASCII log of changes
    def _emit_changes(a: Dict[str, Any], b: Dict[str, Any], path: List[str] = None):
        if path is None:
            path = []
        keys = sorted(set(a.keys()) | set(b.keys()))
        for k in keys:
            pa = a.get(k)
            pb = b.get(k)
            if isinstance(pa, dict) and isinstance(pb, dict):
                _emit_changes(pa, pb, path + [str(k)])
            else:
                if pa != pb:
                    dotted = '.'.join(path + [str(k)])
                    if _is_allowed_path(path + [str(k)]):
                        print(f"PROFILE_APPLY key={dotted} old={pa} new={pb}")
    _emit_changes(before, after)
    return after


def maybe_apply_from_env(cfg: Dict[str, Any]) -> Dict[str, Any]:
    name = os.environ.get('MM_PROFILE')
    if not name:
        return dict(cfg)
    return apply_profile(cfg, name)


