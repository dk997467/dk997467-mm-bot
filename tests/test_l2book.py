"""
Unit tests for Rust-backed mm_orderbook.L2Book.
"""

import math
import pytest

mm = pytest.importorskip("mm_orderbook")


def approx_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def make_book_with_snapshot():
    book = mm.L2Book()
    bids = [(100.0, 2.0), (99.5, 1.0)]  # bids desc
    asks = [(100.5, 1.5), (101.0, 0.8)]  # asks asc
    book.apply_snapshot(bids, asks)
    return book


def test_snapshot_best_bid_ask():
    book = make_book_with_snapshot()

    best_bid = book.best_bid()
    best_ask = book.best_ask()

    assert best_bid is not None
    assert best_ask is not None

    bp, bs = best_bid
    ap, az = best_ask

    assert approx_equal(bp, 100.0)
    assert approx_equal(bs, 2.0)
    assert approx_equal(ap, 100.5)
    assert approx_equal(az, 1.5)


def test_delta_update_and_removal():
    book = make_book_with_snapshot()

    # Add a better bid above current best
    book.apply_delta(bids=[(100.25, 1.2)], asks=[])
    best_bid = book.best_bid()
    assert best_bid is not None
    bp, bs = best_bid
    assert approx_equal(bp, 100.25)
    assert approx_equal(bs, 1.2)

    # Remove current best ask (size <= 0 removes level)
    book.apply_delta(bids=[], asks=[(100.5, 0.0)])
    best_ask = book.best_ask()
    assert best_ask is not None
    ap, az = best_ask
    # Next ask should become 101.0
    assert approx_equal(ap, 101.0)
    assert approx_equal(az, 0.8)


def test_mid_microprice_imbalance_values():
    book = make_book_with_snapshot()

    # mid = (best_bid + best_ask)/2 = (100.0 + 100.5)/2 = 100.25
    mid = book.mid()
    assert mid is not None
    assert approx_equal(mid, 100.25)

    # microprice = bp*(asz/(bs+asz)) + ap*(bs/(bs+asz))
    # bs=2.0, asz=1.5 => total=3.5
    # micro = 100.0*(1.5/3.5) + 100.5*(2.0/3.5) = 100.2857142857...
    micro = book.microprice()
    assert micro is not None
    assert approx_equal(micro, (100.0*(1.5/3.5) + 100.5*(2.0/3.5)))

    # imbalance(depth=5) = (sum_bids - sum_asks) / (sum_bids + sum_asks)
    # sum_bids = 2.0 + 1.0 = 3.0, sum_asks = 1.5 + 0.8 = 2.3
    # imbalance = 0.7 / 5.3 ≈ 0.1320754717
    imb = book.imbalance(5)
    assert approx_equal(imb, (3.0 - 2.3) / (3.0 + 2.3))
