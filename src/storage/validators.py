"""
Validators for hourly summary JSON files.

Provides validation and schema upgrade functionality for E1+ summaries.
"""

from typing import Dict, List, Tuple, Any
from datetime import datetime, timezone


def validate_summary_payload(summary: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate hourly summary payload structure and data integrity.
    
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    # Check required top-level keys
    required_keys = [
        "counts", "hit_rate_by_bin", "queue_wait_cdf_ms", 
        "metadata", "schema_version", "window_utc"
    ]
    
    for key in required_keys:
        if key not in summary:
            errors.append(f"Missing required key: '{key}'")
    
    if errors:  # Early return if missing critical keys
        return False, errors
    
    # Validate counts structure
    counts = summary.get("counts", {})
    count_keys = ["orders", "quotes", "fills"]
    
    for count_key in count_keys:
        if count_key not in counts:
            errors.append(f"Missing counts.{count_key}")
        else:
            value = counts[count_key]
            if not isinstance(value, int) or value < 0:
                errors.append(f"counts.{count_key} must be non-negative integer, got: {value}")
    
    # Validate hit_rate_by_bin structure
    hit_rate_by_bin = summary.get("hit_rate_by_bin", {})
    bins_max_bps = summary.get("bins_max_bps", 50)  # Default fallback
    
    for bin_key, bin_data in hit_rate_by_bin.items():
        # Check bin key is valid
        try:
            bin_value = int(bin_key)
            if bin_value < 0 or bin_value > bins_max_bps:
                errors.append(f"Bin key '{bin_key}' outside valid range [0, {bins_max_bps}]")
        except (ValueError, TypeError):
            errors.append(f"Bin key '{bin_key}' must be string representation of integer")
        
        # Check bin data structure
        if not isinstance(bin_data, dict):
            errors.append(f"Bin data for '{bin_key}' must be dict, got: {type(bin_data)}")
            continue
            
        for required_field in ["count", "fills"]:
            if required_field not in bin_data:
                errors.append(f"Missing {required_field} in bin '{bin_key}'")
            else:
                value = bin_data[required_field]
                if not isinstance(value, int) or value < 0:
                    errors.append(f"bin[{bin_key}].{required_field} must be non-negative integer, got: {value}")
        
        # Logical constraint: fills <= count
        if "count" in bin_data and "fills" in bin_data:
            if bin_data["fills"] > bin_data["count"]:
                errors.append(f"bin[{bin_key}].fills ({bin_data['fills']}) > count ({bin_data['count']})")
    
    # Validate queue_wait_cdf_ms
    cdf = summary.get("queue_wait_cdf_ms", [])
    if not isinstance(cdf, list):
        errors.append(f"queue_wait_cdf_ms must be list, got: {type(cdf)}")
    else:
        prev_p = -1
        prev_v = None
        
        for i, entry in enumerate(cdf):
            if not isinstance(entry, dict):
                errors.append(f"CDF entry {i} must be dict, got: {type(entry)}")
                continue
            
            if "p" not in entry or "v" not in entry:
                errors.append(f"CDF entry {i} missing 'p' or 'v' field")
                continue
            
            p, v = entry["p"], entry["v"]
            
            # Check types
            if not isinstance(p, (int, float)) or not isinstance(v, (int, float)):
                errors.append(f"CDF entry {i}: p and v must be numeric")
                continue
            
            # Check p strictly increasing
            if p <= prev_p:
                errors.append(f"CDF entry {i}: p={p} not strictly greater than previous p={prev_p}")
            
            # Check v non-decreasing
            if prev_v is not None and v < prev_v:
                errors.append(f"CDF entry {i}: v={v} decreasing from previous v={prev_v}")
            
            # Check p in valid range
            if not (0 <= p <= 1):
                errors.append(f"CDF entry {i}: p={p} outside valid range [0, 1]")
            
            prev_p = p
            prev_v = v
    
    # Validate window_utc structure
    window_utc = summary.get("window_utc", {})
    if not isinstance(window_utc, dict):
        errors.append(f"window_utc must be dict, got: {type(window_utc)}")
    else:
        for time_key in ["hour_start", "hour_end"]:
            if time_key not in window_utc:
                errors.append(f"Missing window_utc.{time_key}")
            else:
                time_str = window_utc[time_key]
                if not isinstance(time_str, str) or not time_str.endswith("Z"):
                    errors.append(f"window_utc.{time_key} must be UTC ISO string ending with 'Z'")
                else:
                    try:
                        datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    except ValueError:
                        errors.append(f"window_utc.{time_key} invalid ISO format: {time_str}")
        
        # Check logical ordering
        if "hour_start" in window_utc and "hour_end" in window_utc:
            try:
                start_dt = datetime.fromisoformat(window_utc["hour_start"].replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(window_utc["hour_end"].replace('Z', '+00:00'))
                if start_dt >= end_dt:
                    errors.append(f"window_utc.hour_start ({start_dt}) >= hour_end ({end_dt})")
            except ValueError:
                pass  # Already reported parsing errors above
    
    # Validate metadata structure
    metadata = summary.get("metadata", {})
    if not isinstance(metadata, dict):
        errors.append(f"metadata must be dict, got: {type(metadata)}")
    else:
        required_meta_keys = ["git_sha", "cfg_hash"]
        for meta_key in required_meta_keys:
            if meta_key not in metadata:
                errors.append(f"Missing metadata.{meta_key}")
            else:
                value = metadata[meta_key]
                if not isinstance(value, str) or not value:
                    errors.append(f"metadata.{meta_key} must be non-empty string")
    
    # Validate schema_version
    schema_version = summary.get("schema_version")
    if not isinstance(schema_version, str):
        errors.append(f"schema_version must be string, got: {type(schema_version)}")
    elif not schema_version.startswith("e1."):
        errors.append(f"schema_version must start with 'e1.', got: {schema_version}")
    
    return len(errors) == 0, errors


def upgrade_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upgrade summary to latest schema version, adding missing fields with defaults.
    
    Policy: e1.0 → e1.1 by ensuring all required keys exist.
    Returns upgraded copy without modifying the original.
    """
    # Create deep copy for modification
    upgraded = dict(summary)
    current_version = upgraded.get("schema_version", "e1.0")
    
    # Ensure required keys exist with defaults
    if "bins_max_bps" not in upgraded:
        upgraded["bins_max_bps"] = 50
    
    if "percentiles_used" not in upgraded:
        upgraded["percentiles_used"] = [0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
    
    if "window_utc" not in upgraded:
        # Try to reconstruct from hour_utc if available
        hour_utc = upgraded.get("hour_utc", "")
        if hour_utc and hour_utc.endswith("Z"):
            try:
                hour_dt = datetime.fromisoformat(hour_utc.replace('Z', '+00:00'))
                end_dt = hour_dt.replace(hour=hour_dt.hour + 1) if hour_dt.hour < 23 else hour_dt.replace(day=hour_dt.day + 1, hour=0)
                upgraded["window_utc"] = {
                    "hour_start": hour_utc,
                    "hour_end": end_dt.isoformat() + "Z"
                }
            except ValueError:
                # Fallback to current time if parsing fails
                now_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
                end_utc = now_utc.replace(hour=now_utc.hour + 1) if now_utc.hour < 23 else now_utc.replace(day=now_utc.day + 1, hour=0)
                upgraded["window_utc"] = {
                    "hour_start": now_utc.isoformat() + "Z",
                    "hour_end": end_utc.isoformat() + "Z"
                }
        else:
            # Complete fallback
            now_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            end_utc = now_utc.replace(hour=now_utc.hour + 1) if now_utc.hour < 23 else now_utc.replace(day=now_utc.day + 1, hour=0)
            upgraded["window_utc"] = {
                "hour_start": now_utc.isoformat() + "Z", 
                "hour_end": end_utc.isoformat() + "Z"
            }
    
    if "generated_at_utc" not in upgraded:
        upgraded["generated_at_utc"] = datetime.now(timezone.utc).isoformat() + "Z"
    
    # Set the upgraded schema version
    if current_version == "e1.0":
        upgraded["schema_version"] = "e1.1"
    
    return upgraded


def validate_hourly_summary_file(summary: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Convenience wrapper: upgrade then validate.
    
    Returns validation result for the upgraded summary.
    """
    try:
        upgraded = upgrade_summary(summary)
        return validate_summary_payload(upgraded)
    except Exception as e:
        return False, [f"Error during upgrade/validation: {str(e)}"]
