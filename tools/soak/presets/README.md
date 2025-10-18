# Soak Tuning Presets

Presets are pre-configured tuning adjustments that can be applied to runtime overrides before starting a soak test.

## Available Presets

### `maker_bias_uplift_v1.json`

**Goal:** Increase maker/taker ratio and net_bps without impacting latency.

**Target Metrics:**
- `maker_taker_ratio`: ≥ 0.83
- `net_bps`: ≥ 2.8
- `p95_latency_ms`: ≤ 330ms
- `risk_ratio`: ≤ 0.40

**Changes:**
- **Quoting:**
  - `base_spread_bps_delta`: +0.01 bps (widen spread)
  - `min_interval_ms`: +15ms (reduce rebid frequency)
  - `replace_rate_per_min`: ×0.90 (10% reduction in replacement rate)

- **Impact:**
  - `impact_cap_ratio`: ×0.95 (5% more conservative estimation)
  - `max_delta_ratio`: ×0.95 (5% smaller position deltas)

- **Taker Rescue:**
  - `rescue_max_ratio`: ×0.85 (15% reduction in taker aggressiveness)
  - `min_edge_bps`: +0.5 bps (higher threshold for taker entry)
  - `cooldown_ms`: +250ms (longer cooldown between rescues)

**Expected Impact:** +8–12 percentage points in maker share, improved net_bps.

## Usage

### By Name

```bash
python -m tools.soak.run \
  --iterations 12 \
  --mock \
  --auto-tune \
  --preset maker_bias_uplift_v1
```

### By File Path

```bash
python -m tools.soak.run \
  --iterations 12 \
  --mock \
  --auto-tune \
  --preset-file path/to/custom_preset.json
```

## Preset Format

```json
{
  "description": "Brief description of preset goals",
  "version": "1.0",
  "target_metrics": {
    "maker_taker_ratio": "≥ 0.83",
    "net_bps": "≥ 2.8"
  },
  "changes": {
    "section_name": {
      "param_name": {
        "op": "add",
        "value": 0.05,
        "reason": "Human-readable explanation"
      }
    }
  }
}
```

### Supported Operations

- **`add`:** `dst = (dst or 0) + value`
  - Use for additive adjustments (e.g., +15ms to min_interval_ms)

- **`mul`:** `dst = (dst or 1) * value`
  - Use for multiplicative adjustments (e.g., ×0.90 for 10% reduction)

## Creating Custom Presets

1. Copy `maker_bias_uplift_v1.json` as a template
2. Modify `changes` section with your parameter deltas
3. Update `description` and `target_metrics`
4. Save to `tools/soak/presets/<name>.json`
5. Test with a 12-iteration mock soak

## Validation

After applying a preset, verify:

```bash
# Generate reports
python -m tools.soak.build_reports \
  --src artifacts/soak/latest \
  --out artifacts/soak/latest/reports/analysis

# Check snapshot
cat artifacts/soak/latest/reports/analysis/POST_SOAK_SNAPSHOT.json
```

**Success Criteria (12 iterations, last-8 window):**
- `maker_taker_ratio.median` ≥ target
- `p95_latency_ms.max` ≤ target
- `risk_ratio.median` ≤ target
- `net_bps.median` ≥ target
- `full_apply_ratio` ≥ 0.95 (from delta verification)

## Rollback

Presets are applied at startup and don't persist unless you save `runtime_overrides.json`.

To roll back:
1. Simply run without `--preset` flag
2. Or restore `runtime_overrides.json` from backup

## Integration with Guards

Presets work seamlessly with guards:
- **Debounce:** Prevents rapid oscillation after preset changes
- **Partial Freeze:** Freezes rebid/rescue_taker if latency spikes
- **Edge:** Never frozen, always active

Guards are automatically initialized when guards are available.

## Best Practices

1. **Start Gentle:** Small adjustments (±5–10%) are safer than large ones
2. **Iterate:** Run 12–24 iterations to see the full effect
3. **Monitor:** Check `POST_SOAK_AUDIT.md` for anomalies
4. **Validate:** Ensure `full_apply_ratio` ≥ 0.95 before production
5. **Document:** Update `target_metrics` with measured results

## Troubleshooting

**Q: Preset applied but metrics didn't improve**
- Check `DELTA_VERIFY_REPORT.md` for nested write issues
- Verify guards didn't freeze params (look for `| guards | PARTIAL_FREEZE |`)
- Increase iterations (12 → 24) for clearer trends

**Q: "Preset not found" error**
- Check preset name matches file: `<name>.json`
- Use `--preset-file` with full path for custom locations
- Ensure JSON is valid (use `jq . < preset.json`)

**Q: KPI still below target after preset**
- Try incrementing: add `_v2` with stronger adjustments
- Check for conflicting auto-tune deltas (they can undo preset)
- Review `TUNING_REPORT.json` for skip reasons

## See Also

- `docs/SOAK_NESTED_WRITE_MOCK_GATE.md` - Delta application details
- `tools/soak/guards.py` - Guard logic implementation
- `POST_SOAK_AUDIT.md` - Generated after soak runs

