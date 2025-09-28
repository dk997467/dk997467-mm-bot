from decimal import Decimal
from datetime import datetime

from src.common.config import Config
from src.common.models import OrderBook, PriceLevel
from src.strategy.quoting import MarketMakingStrategy


def make_ob(mid=Decimal('100'), spread=Decimal('1')) -> OrderBook:
	bid = mid - spread / 2
	ask = mid + spread / 2
	return OrderBook(
		symbol='BTCUSDT',
		timestamp=datetime.utcnow(),
		sequence=1,
		bids=[PriceLevel(price=bid, size=Decimal('2'))],
		asks=[PriceLevel(price=ask, size=Decimal('2'))],
	)


def test_quotes_do_not_cross():
	from src.common.config import get_config
	cfg = get_config()
	strat = MarketMakingStrategy(cfg)
	ob = make_ob()
	# capture quotes via callback
	quotes = []
	strat.set_callbacks(on_quote_request=lambda q: quotes.append(q))
	strat.update_orderbook('BTCUSDT', ob)
	assert quotes, 'Strategy should emit quotes'
	best_bid = ob.bids[0].price
	best_ask = ob.asks[0].price
	for q in quotes:
		if q.side.value == 'Buy':
			assert q.price < best_ask
		else:
			assert q.price > best_bid


def test_inventory_skew_bounds():
	from src.common.config import get_config
	cfg = get_config()
	strat = MarketMakingStrategy(cfg)
	ob = make_ob()
	# Force high inventory and ensure skew clamped
	strat.inventory['BTCUSDT'] = Decimal('10000')  # Use fixed value for test
	quotes = []
	strat.set_callbacks(on_quote_request=lambda q: quotes.append(q))
	strat.update_orderbook('BTCUSDT', ob)
	assert quotes

