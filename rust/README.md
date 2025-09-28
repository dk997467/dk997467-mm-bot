# mm_orderbook (Rust + pyo3)

High-performance Level-2 order book implemented in Rust and exposed to Python via pyo3 + maturin.

Build and install

```
# From the rust/ directory
pip install maturin
maturin develop --release
# or build wheel
maturin build --release
```

Python usage

```
from mm_orderbook import L2Book

book = L2Book()
book.apply_snapshot([(100.0, 2.0), (99.5, 1.5)], [(100.5, 1.2), (101.0, 2.0)])
print(book.best_bid())  # (100.0, 2.0)
print(book.best_ask())  # (100.5, 1.2)
print(book.mid())       # 100.25
print(book.microprice())
print(book.imbalance(5))
```

Notes
- apply_delta supports (price, size), where size <= 0 removes level
- Bids are maintained in descending price order; asks ascending
- Functions return None if not computable
