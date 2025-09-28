from src.guards.runtime import RuntimeGuard
from src.common.config import RuntimeGuardConfig


def test_per_symbol_overrides_reject_rate():
    cfg = RuntimeGuardConfig(
        enabled=True,
        order_reject_rate_max=0.2,
        per_symbol={
            'BTCUSDT': {'order_reject_rate_max': 0.1},
            'ETHUSDT': {'order_reject_rate_max': 0.3},
        },
        consecutive_breaches_to_pause=1,
        hysteresis_bad_required=1,
        hysteresis_good_required=1,
    )
    g = RuntimeGuard(cfg)
    # push rejects
    g.on_reject('A', 0.0)
    # BTC should breach (0.5 > 0.1)
    reason_btc = g.evaluate(now=0.0, symbol='BTCUSDT')
    assert reason_btc != 0
    # ETH should not breach (0.5 < 0.3 is false -> 0.5 > 0.3 -> breach). To make ETH pass, add success
    g.on_send_ok('B', 0.0)
    # now rate = 0.5 -> still > 0.3, so to ensure ETH no breach reduce to 0.25
    g.on_send_ok('C', 0.0)
    rate_eth_reason = g.evaluate(now=0.0, symbol='ETHUSDT')
    # After two oks and one reject => 1/3 ~= 0.333..., still > 0.3; add one more ok to go 1/4=0.25
    g.on_send_ok('D', 0.0)
    rate_eth_reason2 = g.evaluate(now=0.0, symbol='ETHUSDT')
    assert rate_eth_reason2 == 0

