from decimal import Decimal
from src.common.config import Config
from src.risk.risk_manager import RiskManager
from src.common.models import Side


def make_config() -> Config:
	from src.common.config import get_config
	return get_config()


def test_daily_loss_kill_switch():
	cfg = make_config()
	rm = RiskManager(cfg)
	# Overshoot daily loss
	rm.update_pnl(realized_pnl=Decimal(-300) * Decimal('1.1'))  # Use fixed value for test
	assert rm.kill_switch_triggered


def test_cancel_budget_enforcement():
	cfg = make_config()
	rm = RiskManager(cfg)
	symbol = cfg.trading.symbols[0]
	for _ in range(91):  # Use fixed value for test
		rm.record_cancel(symbol)
	assert rm.cancel_counts[symbol] >= 90
	assert not rm.can_cancel_order(symbol)


def test_position_exposure_cap():
	cfg = make_config()
	rm = RiskManager(cfg)
	symbol = cfg.trading.symbols[0]
	price = Decimal('50000')
	size = Decimal(5000) / price * Decimal('1.1')  # Use fixed value for test
	ok, reason = rm.can_place_order(symbol, Side.BUY, size, price)
	assert not ok

