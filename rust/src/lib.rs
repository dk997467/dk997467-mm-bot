use indexmap::IndexMap;
use ordered_float::OrderedFloat;
use pyo3::prelude::*;
use pyo3::types::PyModuleMethods;

#[pyclass]
#[derive(Default, Clone)]
pub struct L2Book {
    // Используем OrderedFloat<f64> в качестве ключа, чтобы разрешить хеширование
    bids: IndexMap<OrderedFloat<f64>, f64>,
    asks: IndexMap<OrderedFloat<f64>, f64>,
}

#[pymethods]
impl L2Book {
    #[new]
    pub fn new() -> Self {
        Self {
            bids: IndexMap::new(),
            asks: IndexMap::new(),
        }
    }

    pub fn clear(&mut self) {
        self.bids.clear();
        self.asks.clear();
    }

    pub fn apply_snapshot(&mut self, bids: Vec<(f64, f64)>, asks: Vec<(f64, f64)>) -> PyResult<()> {
        self.clear();
        // Insert bids (descending order)
        let mut bb = bids;
        bb.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
        for (p, s) in bb.into_iter() {
            if s > 0.0 {
                // Оборачиваем ключ p в OrderedFloat
                self.bids.insert(OrderedFloat(p), s);
            }
        }
        // Insert asks (ascending order)
        let mut aa = asks;
        aa.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
        for (p, s) in aa.into_iter() {
            if s > 0.0 {
                // Оборачиваем ключ p в OrderedFloat
                self.asks.insert(OrderedFloat(p), s);
            }
        }
        Ok(())
    }

    // Delta format: (price, size). size<=0 removes the level
    pub fn apply_delta(&mut self, bids: Vec<(f64, f64)>, asks: Vec<(f64, f64)>) -> PyResult<()> {
        for (p, s) in bids.into_iter() {
            if s > 0.0 {
                // Оборачиваем ключ p в OrderedFloat
                self.bids.insert(OrderedFloat(p), s);
            } else {
                // Оборачиваем ключ p в OrderedFloat для поиска и удаления
                self.bids.swap_remove(&OrderedFloat(p));
            }
        }
        for (p, s) in asks.into_iter() {
            if s > 0.0 {
                // Оборачиваем ключ p в OrderedFloat
                self.asks.insert(OrderedFloat(p), s);
            } else {
                // Оборачиваем ключ p в OrderedFloat для поиска и удаления
                self.asks.swap_remove(&OrderedFloat(p));
            }
        }
        // Re-sort to ensure order
        self.reorder();
        Ok(())
    }

    #[getter]
    pub fn best_bid(&self) -> Option<(f64, f64)> {
        // Разыменовываем ключ p, чтобы вернуть f64
        self.bids.iter().next().map(|(p, s)| (p.0, *s))
    }

    #[getter]
    pub fn best_ask(&self) -> Option<(f64, f64)> {
        // Разыменовываем ключ p, чтобы вернуть f64
        self.asks.iter().next().map(|(p, s)| (p.0, *s))
    }

    pub fn mid(&self) -> Option<f64> {
        match (self.best_bid(), self.best_ask()) {
            (Some((bp, _)), Some((ap, _))) if bp > 0.0 && ap > 0.0 => Some((bp + ap) / 2.0),
            _ => None,
        }
    }

    pub fn microprice(&self) -> Option<f64> {
        let (bid, ask) = (self.best_bid(), self.best_ask());
        if let (Some((bp, bs)), Some((ap, asz))) = (bid, ask) {
            let total = bs + asz;
            if total > 0.0 {
                let bw = asz / total;
                let aw = bs / total;
                return Some(bp * bw + ap * aw);
            }
        }
        self.mid()
    }

    pub fn imbalance(&self, depth: usize) -> f64 {
        let bid_vol: f64 = self.bids.iter().take(depth).map(|(_, s)| *s).sum();
        let ask_vol: f64 = self.asks.iter().take(depth).map(|(_, s)| *s).sum();
        let tot = bid_vol + ask_vol;
        if tot == 0.0 {
            0.0
        } else {
            (bid_vol - ask_vol) / tot
        }
    }

    fn reorder(&mut self) {
        // Rebuild keeping order: bids desc, asks asc
        let mut bb: Vec<(f64, f64)> = self.bids.iter().map(|(p, s)| (p.0, *s)).collect();
        let mut aa: Vec<(f64, f64)> = self.asks.iter().map(|(p, s)| (p.0, *s)).collect();
        bb.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
        // FIX: Asks should be ascending
        aa.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
        self.bids.clear();
        self.asks.clear();
        for (p, s) in bb.into_iter() {
            self.bids.insert(OrderedFloat(p), s);
        }
        for (p, s) in aa.into_iter() {
            self.asks.insert(OrderedFloat(p), s);
        }
    }
}

#[pymodule]
fn mm_orderbook(m: &Bound<PyModule>) -> PyResult<()> {
    m.add_pyclass::<L2Book>()?;
    Ok(())
}
