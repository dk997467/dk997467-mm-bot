import json
from typing import Dict, Any, List, Tuple


def _finite(x: float) -> float:
    try:
        import math
        v = float(x)
        if math.isfinite(v):
            return v
        return 0.0
    except Exception:
        return 0.0


class VirtualLedger:
    def __init__(self, base_ccy: str = 'EUR'):
        self.base_ccy = str(base_ccy)
        self.positions: Dict[str, float] = {}
        self.cash: float = 0.0
        self.unrealized: float = 0.0
        self.equity: float = 0.0
        # daily aggregates
        self._day: str = ''
        self._daily: Dict[str, float] = {
            'pnl': 0.0,
            'fees': 0.0,
            'rebates': 0.0,
            'turnover': 0.0,
        }
        self.daily_reports: List[Dict[str, Any]] = []
        self.equity_series: List[Dict[str, Any]] = []

    def on_fill(self, utc_ts: str, symbol: str, side: str, price: float, qty: float, fee_bps: float, maker_rebate_bps: float = 0.0) -> None:
        # Initialize day
        day = str(utc_ts)[:10]
        if not self._day:
            self._day = day
        self._rollover_if_needed(day)
        s = str(symbol)
        sd = 1.0 if str(side).upper().startswith('B') else -1.0
        p = _finite(price)
        q = _finite(qty)
        notional = p * abs(q)
        fee = abs(notional) * _finite(fee_bps) / 1e4
        rebate = abs(notional) * _finite(maker_rebate_bps) / 1e4
        # Position update
        pos_old = float(self.positions.get(s, 0.0))
        pos_new = pos_old + sd * q
        self.positions[s] = pos_new
        # Cash update: buy -> -notional - fee + rebate; sell -> +notional - fee + rebate
        self.cash += sd * notional * -1.0  # buy negative cash, sell positive
        self.cash -= fee
        self.cash += rebate
        # Realized PnL recognized on closing trades via FIFO? Simplify: mark realized on opposite sign change for quantity portion
        realized = 0.0
        if pos_old != 0.0 and (pos_old > 0 and sd < 0 or pos_old < 0 and sd > 0):
            # Close portion up to min(abs(pos_old), qty)
            close_qty = min(abs(pos_old), q)
            # Assume flat cost basis at zero for simplicity; realized captured via cash movement already
            # Therefore realized remains 0; fees/rebates included in cash
            realized = 0.0
        # Daily aggregates
        self._daily['fees'] += fee
        self._daily['rebates'] += rebate
        self._daily['turnover'] += abs(notional)
        self._daily['pnl'] += realized

    def mark_to_market(self, utc_ts: str, mid_by_symbol: Dict[str, float]) -> None:
        # Update unrealized and equity
        u = 0.0
        for s in sorted(self.positions.keys()):
            pos = float(self.positions.get(s, 0.0))
            mid = _finite(mid_by_symbol.get(s, 0.0)) if isinstance(mid_by_symbol, dict) else 0.0
            u += pos * mid
        self.unrealized = _finite(u)
        self.equity = _finite(self.cash + self.unrealized)
        self.equity_series.append({'ts': str(utc_ts), 'equity': self.equity})

    def daily_close(self, utc_date: str) -> Dict[str, Any]:
        # Close day: capture aggregates + equity snapshot
        rep = {
            'date': str(utc_date),
            'fees': _finite(self._daily['fees']),
            'pnl': _finite(self._daily['pnl']),
            'rebates': _finite(self._daily['rebates']),
            'turnover': _finite(self._daily['turnover']),
            'equity': _finite(self.equity),
        }
        self.daily_reports.append(rep)
        # Reset daily counters; keep positions and cash
        self._daily = {'pnl': 0.0, 'fees': 0.0, 'rebates': 0.0, 'turnover': 0.0}
        self._day = ''
        return rep

    def _rollover_if_needed(self, day: str) -> None:
        if self._day and day != self._day:
            # auto-close previous day
            self.daily_close(self._day)
            self._day = day


