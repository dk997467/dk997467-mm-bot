import pytest
from decimal import Decimal
from datetime import datetime

from src.marketdata.orderbook import OrderBookManager
from src.common.models import OrderBook, PriceLevel


def make_snapshot(symbol: str, seq: int):
	return OrderBook(
		symbol=symbol,
		timestamp=datetime.utcnow(),
		sequence=seq,
		bids=[PriceLevel(price=Decimal('100'), size=Decimal('2')), PriceLevel(price=Decimal('99'), size=Decimal('1'))],
		asks=[PriceLevel(price=Decimal('101'), size=Decimal('2')), PriceLevel(price=Decimal('102'), size=Decimal('1'))],
	)


def test_snapshot_updates_and_invariants():
	obm = OrderBookManager('BTCUSDT', max_depth=2)
	snap = make_snapshot('BTCUSDT', 1)
	assert obm.update_from_snapshot(snap)
	assert obm.is_synced
	assert not obm.is_crossed()
	mid = obm.get_mid_price()
	assert mid == Decimal('100.5')
	spread = obm.get_spread()
	assert spread == Decimal('1')


def test_delta_update_and_gap_detection():
	obm = OrderBookManager('BTCUSDT')
	obm.update_from_snapshot(make_snapshot('BTCUSDT', 10))
	# Apply in-sequence delta
	delta_ok = {'u': 11, 'b': [['100', '3']], 'a': [['101', '1']]}
	assert obm.update_from_delta(delta_ok)
	# Apply out-of-sequence delta -> should flag resync
	delta_gap = {'u': 13, 'b': [['100', '1']]}
	assert not obm.update_from_delta(delta_gap)
	assert obm.needs_resync

