#!/usr/bin/env python3
"""
Demo script for E2 Polish features: progress, effective_w4, cache stats.
"""

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.research.calibrate import (
    sample_candidates, evaluate_candidate, params_hash,
    DEFAULT_PARAM_BOUNDS
)


def demo_progress_and_cache():
    """Demo progress logging and cache statistics."""
    print("🔧 E2 Polish Features Demo")
    print("=" * 40)
    
    # Create mock LIVE distributions without live_maker (to test effective_w4)
    live_distributions = {
        "queue_wait_cdf_ms": [
            {"p": 0.25, "v": 120.0},
            {"p": 0.5, "v": 180.0},
            {"p": 0.75, "v": 240.0},
            {"p": 0.9, "v": 300.0}
        ],
        "hit_rate_by_bin": {
            "0": {"count": 200, "fills": 60},
            "5": {"count": 180, "fills": 45},
            "10": {"count": 160, "fills": 32}
        },
        "live_hit": 0.30,
        "live_maker": None  # Missing maker data - should trigger effective_w4=0
    }
    
    print(f"📊 LIVE distributions setup:")
    print(f"   • Hit rate: {live_distributions['live_hit']:.3f}")
    print(f"   • Maker share: {live_distributions['live_maker']} (missing)")
    
    # Generate some candidates (including duplicates for cache testing)
    bounds = DEFAULT_PARAM_BOUNDS.copy()
    candidates = sample_candidates("random", 8, seed=42, bounds=bounds)
    
    # Add duplicate candidate to test caching
    candidates.append(candidates[0].copy())  # Exact duplicate
    
    print(f"🎯 Generated {len(candidates)} candidates (including 1 duplicate for cache test)")
    
    # Simulate evaluation with progress and cache tracking
    cache = {}
    cache_hits = 0
    cache_misses = 0
    evaluated_candidates = []
    
    weights = {"KS_queue": 1.0, "KS_bins": 1.0, "L_hit": 1.0, "L_maker": 0.5, "L_reg": 1.0}
    
    print(f"\n🧮 Evaluating candidates with cache tracking:")
    print(f"   {'#':<3} {'Hash':<12} {'Cache':<8} {'w4_eff':<8} {'TotalLoss':<10}")
    print(f"   {'-'*3} {'-'*12} {'-'*8} {'-'*8} {'-'*10}")
    
    start_time = time.time()
    
    for i, candidate in enumerate(candidates):
        # Progress simulation (every 3 candidates to see effect in small demo)
        if (i + 1) % 3 == 0 or i == 0:
            elapsed = time.time() - start_time
            progress_pct = (i + 1) / len(candidates) * 100
            
            if i > 0 and elapsed > 0:
                rate = (i + 1) / elapsed
                remaining = len(candidates) - (i + 1)
                eta_seconds = remaining / rate if rate > 0 else 0
                eta_str = f"ETA={eta_seconds:.1f}s"
            else:
                eta_str = "ETA=calculating"
            
            print(f"📊 Progress: {i+1}/{len(candidates)} ({progress_pct:.1f}%) elapsed={elapsed:.1f}s {eta_str}")
        
        # Cache logic
        cand_hash = params_hash(candidate)
        cache_status = "HIT" if cand_hash in cache else "MISS"
        
        if cand_hash in cache:
            cache_hits += 1
            # Use cached result
            sim_distributions = cache[cand_hash]
        else:
            cache_misses += 1
            # Generate new SIM result
            param_sum = sum(candidate.values())
            sim_distributions = {
                "queue_wait_cdf_ms": [
                    {"p": 0.25, "v": 125.0 + param_sum * 0.01},
                    {"p": 0.5, "v": 185.0 + param_sum * 0.015},
                    {"p": 0.75, "v": 245.0 + param_sum * 0.02},
                    {"p": 0.9, "v": 305.0 + param_sum * 0.025}
                ],
                "hit_rate_by_bin": {
                    "0": {"count": 200, "fills": max(1, int(55 + param_sum * 0.001))},
                    "5": {"count": 180, "fills": max(1, int(40 + param_sum * 0.001))},
                    "10": {"count": 160, "fills": max(1, int(28 + param_sum * 0.001))}
                },
                "sim_hit": max(0.1, 0.28 + param_sum * 0.00001),
                "sim_maker": max(0.05, 0.22 + param_sum * 0.00001)
            }
            cache[cand_hash] = sim_distributions
        
        # Evaluate candidate
        loss_result = evaluate_candidate(
            candidate, live_distributions, weights,
            reg_l2=0.0, baseline_params=None, sim_distributions=sim_distributions
        )
        
        if loss_result:
            evaluated_candidates.append((candidate, sim_distributions, loss_result))
            
            w4_eff = loss_result.get("w4_effective", weights["L_maker"])
            total_loss = loss_result["TotalLoss"]
            
            print(f"   {i+1:<3} {cand_hash:<12} {cache_status:<8} {w4_eff:<8.1f} {total_loss:<10.6f}")
    
    total_time = time.time() - start_time
    
    print(f"\n📈 Evaluation Summary:")
    print(f"   • Total candidates: {len(candidates)}")
    print(f"   • Successfully evaluated: {len(evaluated_candidates)}")
    print(f"   • Cache hits: {cache_hits}")
    print(f"   • Cache misses: {cache_misses}")
    print(f"   • Cache hit rate: {cache_hits/(cache_hits+cache_misses)*100:.1f}%")
    print(f"   • Total time: {total_time:.2f}s")
    
    # Check effective w4 behavior
    if evaluated_candidates:
        first_loss = evaluated_candidates[0][2]
        effective_w4 = first_loss.get("w4_effective", "not_found")
        
        print(f"\n⚙️  effective_w4 demonstration:")
        print(f"   • live_maker: {live_distributions['live_maker']}")
        print(f"   • Original L_maker weight: {weights['L_maker']}")
        print(f"   • Effective w4: {effective_w4}")
        print(f"   • L_maker loss component: {first_loss['L_maker']}")
        
        if live_distributions['live_maker'] is None:
            assert effective_w4 == 0.0, "effective_w4 should be 0 when live_maker is None"
            assert first_loss['L_maker'] == 0.0, "L_maker should be 0 when live_maker is None"
            print(f"   ✅ Correctly set effective_w4=0 due to missing live_maker")
        
    # Mock early stopping scenario
    print(f"\n⏱️  Early stopping demo:")
    max_secs = 0.5  # Very short limit
    if total_time > max_secs:
        print(f"   • Time limit: {max_secs}s")
        print(f"   • Actual time: {total_time:.2f}s")
        print(f"   • Would stop early: True")
        print(f"   • Message: 'Early stop at X/{len(candidates)} candidates (time limit {max_secs}s reached)'")
    else:
        print(f"   • Time limit: {max_secs}s")
        print(f"   • Actual time: {total_time:.2f}s")
        print(f"   • Would stop early: False")
    
    # Mock report metadata
    print(f"\n📋 Report metadata example:")
    metadata = {
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "stopped_early": total_time > max_secs,
        "w4_effective": effective_w4,
        "weights": weights
    }
    
    print(json.dumps(metadata, indent=2))
    
    return metadata


if __name__ == "__main__":
    demo_progress_and_cache()
    print(f"\n✅ E2 Polish demo completed successfully!")
