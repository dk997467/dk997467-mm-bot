from typing import Dict, Optional, Tuple


class SimOrder:
    def __init__(self, cl_id: str, symbol: str, side: str, price: float, size: float, ts_ms: int):
        self.cl_id = str(cl_id)
        self.symbol = str(symbol)
        self.side = str(side)
        self.price = float(price)
        self.size = float(size)
        self.ts_ms = int(ts_ms)
        self.state = "New"


class SimBroker:
    def __init__(self):
        self._orders: Dict[str, SimOrder] = {}

    def place(self, cl_id: str, symbol: str, side: str, price: float, size: float, ts_ms: int) -> bool:
        if cl_id in self._orders:
            return False
        self._orders[cl_id] = SimOrder(cl_id, symbol, side, price, size, ts_ms)
        return True

    def replace(self, cl_id: str, price: Optional[float], size: Optional[float], ts_ms: int) -> bool:
        o = self._orders.get(cl_id)
        if not o or o.state not in ("New", "PartiallyFilled"):
            return False
        if price is not None:
            o.price = float(price)
        if size is not None:
            o.size = float(size)
        o.ts_ms = int(ts_ms)
        o.state = "Replaced"
        return True

    def cancel(self, cl_id: str, ts_ms: int) -> bool:
        o = self._orders.get(cl_id)
        if not o or o.state in ("Cancelled", "Filled"):
            return False
        o.state = "Cancelled"
        o.ts_ms = int(ts_ms)
        return True

    def fill(self, cl_id: str, ts_ms: int) -> bool:
        o = self._orders.get(cl_id)
        if not o or o.state in ("Cancelled", "Filled"):
            return False
        o.state = "Filled"
        o.ts_ms = int(ts_ms)
        return True

    def get(self, cl_id: str) -> Optional[SimOrder]:
        return self._orders.get(cl_id)

    def active(self) -> Dict[str, SimOrder]:
        return {k: v for k, v in self._orders.items() if v.state in ("New", "Replaced", "PartiallyFilled")}


