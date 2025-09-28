from src.strategy.tuner import compute_walkforward_splits
from datetime import datetime, timezone

start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
end = datetime(2024, 1, 3, 0, 0, tzinfo=timezone.utc)

splits = compute_walkforward_splits(start, end, train_days=1, validate_hours=12)

print(f'Splits: {len(splits)}')
for i, s in enumerate(splits):
    print(f'Split {i}: Train {s["train_start"]} -> {s["train_end"]}, Validate {s["validate_start"]} -> {s["validate_end"]}')

print("\n--- 24h validation ---")
start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
end = datetime(2024, 1, 7, 0, 0, tzinfo=timezone.utc)

splits = compute_walkforward_splits(start, end, train_days=2, validate_hours=24)

print(f'Splits: {len(splits)}')
for i, s in enumerate(splits):
    print(f'Split {i}: Train {s["train_start"]} -> {s["train_end"]}, Validate {s["validate_start"]} -> {s["validate_end"]}')
