#!/usr/bin/env python3
"""Anomaly detection using MAD (Median Absolute Deviation)."""
from __future__ import annotations
from typing import List


def _median(seq: List[float]) -> float:
    """Calculate median of sequence."""
    if not seq:
        return 0.0
    
    sorted_seq = sorted(seq)
    n = len(sorted_seq)
    
    if n % 2 == 1:
        return sorted_seq[n // 2]
    else:
        return (sorted_seq[n // 2 - 1] + sorted_seq[n // 2]) / 2.0


def _mad(seq: List[float]) -> float:
    """
    Calculate Median Absolute Deviation.
    
    Args:
        seq: Sequence of values
    
    Returns:
        MAD value
    """
    if not seq:
        return 0.0
    
    med = _median(seq)
    abs_deviations = [abs(x - med) for x in seq]
    
    return _median(abs_deviations)


def detect_anomalies(seq: List[float], k: float = 3.0) -> List[int]:
    """
    Detect anomalies using MAD method.
    
    Args:
        seq: Sequence of values
        k: Threshold multiplier (default: 3.0)
    
    Returns:
        List of indices of detected anomalies
    """
    if not seq or len(seq) < 3:
        return []
    
    med = _median(seq)
    mad = _mad(seq)
    
    # If MAD is 0, no anomalies can be detected
    if mad == 0:
        return []
    
    anomalies = []
    
    for i, x in enumerate(seq):
        if abs(x - med) > k * mad:
            anomalies.append(i)
    
    return anomalies
