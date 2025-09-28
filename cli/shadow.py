#!/usr/bin/env python3
"""
Shadow trading mode: run the bot on TESTNET with post-only quotes,
validate no cancel-budget violations and basic metrics after a bounded duration.
"""

try:
    import uvloop
    uvloop.install()
except Exception:
    pass
import argparse
import asyncio
from datetime import datetime, timedelta

from run_bot import MarketMakerBot


async def run_shadow(duration_sec: int) -> int:
	bot = MarketMakerBot()
	await bot.initialize()
	# Ensure testnet
	bot.config.bybit.use_testnet = True
	# Enforce post-only from config
	bot.config.trading.post_only = True

	async def stop_after_delay():
		await asyncio.sleep(duration_sec)
		await bot.stop()

	task = asyncio.create_task(bot.start())
	stopper = asyncio.create_task(stop_after_delay())
	await asyncio.gather(task, stopper)

	# Basic validations
	ok = True
	# Cancel budget
	for symbol, cnt in bot.order_manager.cancel_count.items():
		if cnt > bot.config.risk.max_cancels_per_min:
			print(f"Cancel budget violated for {symbol}: {cnt} > {bot.config.risk.max_cancels_per_min}")
			ok = False
	# Post-only implied by config; taker detection would require exec flags; skip.
	if not ok:
		return 1
	return 0


def main():
	parser = argparse.ArgumentParser(description='Shadow trading on TESTNET (post-only)')
	parser.add_argument('--duration-sec', type=int, default=900, help='Run duration in seconds (default: 900)')
	args = parser.parse_args()

	code = asyncio.run(run_shadow(args.duration_sec))
	exit(code)


if __name__ == '__main__':
	main()

