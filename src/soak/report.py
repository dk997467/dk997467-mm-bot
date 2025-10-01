from __future__ import annotations

from src.common.artifacts import write_json_atomic
from dataclasses import dataclass, asdict
from typing import Dict, Any


@dataclass
class SoakReport:
    warn_count: int
    fail_count: int
    rollback_steps: int
    mttr_sec: float
    phase_uptime: Dict[str, float]
    canary_passed: bool

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # ensure plain types
        d["warn_count"] = int(self.warn_count)
        d["fail_count"] = int(self.fail_count)
        d["rollback_steps"] = int(self.rollback_steps)
        d["mttr_sec"] = float(self.mttr_sec)
        d["canary_passed"] = bool(self.canary_passed)
        # phase_uptime keys are strings, values float seconds
        d["phase_uptime"] = {str(k): float(v) for k, v in (self.phase_uptime or {}).items()}
        return d

    def dump_json(self, path: str) -> None:
        write_json_atomic(path, self.to_dict())

