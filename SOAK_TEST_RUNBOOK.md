# 🔧 Soak Test Runbook & Troubleshooting Guide

**Version:** 1.0  
**Last Updated:** 2025-10-01  
**Status:** Production Ready

---

## 📋 Quick Reference

| Issue | Symptom | Page |
|-------|---------|------|
| Memory Leak | RSS growing unbounded | [§1](#1-memory-leak-detection) |
| WebSocket Issues | Frequent reconnections | [§2](#2-websocket-connection-issues) |
| Orphan Orders | Orders stuck on exchange | [§3](#3-orphan-orders) |
| Disk Full | Artifacts filling up | [§4](#4-disk-space-exhaustion) |
| Process Zombies | Zombie processes accumulating | [§5](#5-zombie-processes) |
| High Latency | Slow REST API calls | [§6](#6-high-rest-api-latency) |
| Crash/Hang | Bot stops responding | [§7](#7-bot-crash-or-hang) |
| Security Alerts | CVE vulnerabilities detected | [§8](#8-security-vulnerabilities) |

---

## 1. Memory Leak Detection

### Symptoms
- RSS (Resident Set Size) growing continuously over time
- `resources.analysis.json` shows `memory_leak_detected: true`
- System becomes sluggish after several hours

### Diagnosis

**Check resource monitor output:**
```bash
# Extract and view analysis
cat artifacts/soak/resources.analysis.json | python -m json.tool

# Look for:
{
  "memory_leak_detected": true,
  "memory_growth_mb_per_hour": 50.5,  # > 10 MB/h = leak
  "memory_stats": {
    "rss_start_mb": 150,
    "rss_end_mb": 1200,  # Large increase
    "rss_max_mb": 1250
  }
}
```

**Check specific components:**
```bash
# Search for memory-related errors in logs
grep -i "memory\|oom\|allocation" artifacts/soak/soak_windows.log

# Check Python garbage collection stats (if instrumented)
grep -i "gc\|garbage" artifacts/soak/soak_windows.log
```

### Root Cause Analysis

**Common culprits:**
1. **Accumulating data structures** (lists, dicts that never get cleared)
2. **File handles not closed** (especially in error paths)
3. **Circular references** preventing garbage collection
4. **C extension leaks** (PyO3/Rust bindings)

**Investigation steps:**
```bash
# Find all file open operations without context managers
grep -rn "open(" src/ | grep -v "with\|#"

# Find list/dict accumulations
grep -rn "\.append\|\.extend\|\[\]" src/ | grep -v "#"

# Check for missing __del__ or cleanup methods
grep -rn "class.*:" src/ -A 20 | grep -E "(def __init__|def __del__)"
```

### Mitigation

**Immediate (during soak test):**
```bash
# Restart test if memory > 2GB RSS
# Monitor: task_manager or ps
tasklist | findstr python  # Windows
ps aux | grep python       # Linux
```

**Long-term fixes:**
1. **Add explicit cleanup:**
   ```python
   # Example: Clear old data periodically
   if len(self.historical_data) > 10000:
       self.historical_data = self.historical_data[-5000:]
   ```

2. **Use weak references:**
   ```python
   import weakref
   self.cache = weakref.WeakValueDictionary()
   ```

3. **Profile with `tracemalloc`:**
   ```python
   import tracemalloc
   tracemalloc.start()
   # ... run code ...
   snapshot = tracemalloc.take_snapshot()
   top_stats = snapshot.statistics('lineno')
   for stat in top_stats[:10]:
       print(stat)
   ```

---

## 2. WebSocket Connection Issues

### Symptoms
- Frequent reconnection attempts
- `ws_reconnect_attempts_total` metric increasing rapidly
- Gaps in order book data
- Log shows: `[ERROR] WebSocket disconnected`

### Diagnosis

**Check reconnection metrics:**
```bash
# Prometheus query (if available)
rate(ws_reconnect_attempts_total[5m])

# Or check logs for reconnection pattern
grep -E "reconnect|WebSocket.*connect" artifacts/soak/soak_windows.log | tail -n 50
```

**Check backoff behavior:**
```bash
# Should see exponential delays (1s, 2s, 4s, 8s, ...)
grep -E "backoff.*delay|reconnect.*attempt" artifacts/soak/soak_windows.log
```

### Root Cause Analysis

**Common causes:**
1. **Network instability** (ISP, firewall, proxy)
2. **Exchange maintenance** (Bybit scheduled downtime)
3. **Rate limiting** (too many connections)
4. **Keepalive timeout** (no ping/pong heartbeat)

**Investigation:**
```bash
# Check for network errors
grep -i "timeout\|connection refused\|network" artifacts/soak/soak_windows.log

# Check for rate limit responses
grep -i "rate limit\|429\|too many" artifacts/soak/soak_windows.log

# Check ping/pong heartbeat
grep -i "ping\|pong\|heartbeat" artifacts/soak/soak_windows.log
```

### Mitigation

**Immediate:**
```yaml
# Increase max_reconnect_delay if hitting max too fast
websocket:
  max_reconnect_delay: 120.0  # Increase from 60s to 120s
```

**Long-term:**
1. **Verify exchange status:**
   - Check Bybit status page: https://bybit-exchange.github.io/docs/status/
   
2. **Tune heartbeat:**
   ```python
   # Reduce heartbeat interval if timeout too long
   heartbeat_interval: 20  # Reduce from 30s to 20s
   ```

3. **Add connection health check:**
   ```python
   # Monitor last_message_time
   if time.time() - self._last_message_time > 60:
       log.warning("No messages for 60s, triggering reconnect")
       await self._reconnect()
   ```

---

## 3. Orphan Orders

### Symptoms
- Orders visible on Bybit UI but not in bot state
- Balance discrepancies
- `cancel_all_orders()` not called in shutdown logs

### Diagnosis

**Check shutdown sequence:**
```bash
# Look for cancel_all_orders in shutdown
grep -A 20 "Shutting down\|stop()" artifacts/soak/soak_windows.log | grep cancel_all

# Expected output:
# [SHUTDOWN] Cancelling all active orders...
# [SHUTDOWN] Cancelled X orders
```

**Check exchange order history:**
```bash
# Manual check via Bybit API or UI
# Look for orders placed during test window but not closed
```

### Root Cause Analysis

**Common causes:**
1. **Abrupt termination** (killed before graceful shutdown)
2. **Network failure** during shutdown
3. **Exception in cancel_all_orders()**
4. **Timeout in shutdown sequence**

**Investigation:**
```bash
# Check if shutdown completed
grep -E "shutdown.*complete|exit.*0" artifacts/soak/soak_windows.log | tail -n 5

# Check for exceptions during shutdown
grep -A 10 "cancel_all_orders" artifacts/soak/soak_windows.log | grep -i "error\|exception"
```

### Mitigation

**Immediate (manual cleanup):**
```python
# Run manual cancel script
python scripts/emergency_cancel_all.py --api-key $KEY --api-secret $SECRET
```

**Prevention:**
1. **Increase shutdown timeout:**
   ```python
   # In cli/run_bot.py
   await asyncio.wait_for(bot.stop(), timeout=60.0)  # Increase from 30s
   ```

2. **Add retry logic to cancel_all_orders:**
   ```python
   async def cancel_all_orders(self, max_retries=3):
       for attempt in range(max_retries):
           try:
               # ... cancel logic ...
               break
           except Exception as e:
               if attempt == max_retries - 1:
                   raise
               await asyncio.sleep(2 ** attempt)
   ```

3. **Persist order state:**
   ```python
   # Save active orders to disk periodically
   with open('active_orders.json', 'w') as f:
       json.dump(self.active_orders, f)
   ```

---

## 4. Disk Space Exhaustion

### Symptoms
- CI fails with "No space left on device"
- `_check_disk_space()` warnings in logs
- Artifacts > 5GB

### Diagnosis

**Check disk usage:**
```bash
# Windows
dir artifacts /s | findstr "bytes"

# Linux
du -sh artifacts/
df -h
```

**Check log rotation:**
```bash
# Count log files per step
ls -l artifacts/ | wc -l

# Check for cleanup events
grep "_cleanup_old_logs\|aggressive cleanup" artifacts/soak/soak_windows.log
```

### Root Cause Analysis

**Common causes:**
1. **Log rotation not working** (bug in cleanup logic)
2. **Large individual files** (not caught by rotation)
3. **Test data accumulation** (CSV, JSON outputs)

**Investigation:**
```bash
# Find largest files
find artifacts/ -type f -exec du -h {} + | sort -rh | head -n 20

# Check cleanup frequency
grep -c "cleanup_old_logs" artifacts/soak/soak_windows.log
```

### Mitigation

**Immediate:**
```bash
# Manual cleanup
rm -rf artifacts/old_runs/
# Or keep only last 3 runs
ls -t artifacts/ | tail -n +4 | xargs rm -rf
```

**Long-term:**
1. **Decrease MAX_LOG_FILES_PER_STEP:**
   ```python
   MAX_LOG_FILES_PER_STEP = 3  # Reduce from 5
   ```

2. **Add log compression:**
   ```python
   import gzip
   with gzip.open('log.gz', 'wt') as f:
       f.write(log_content)
   ```

3. **Stream logs to remote storage:**
   ```python
   # Send logs to S3/Azure Blob instead of local disk
   ```

---

## 5. Zombie Processes

### Symptoms
- `ps` shows `<defunct>` processes
- Process count keeps growing
- CI runner becomes sluggish

### Diagnosis

**Check for zombies:**
```bash
# Windows
tasklist /FI "STATUS eq Not Responding"

# Linux
ps aux | grep "<defunct>"
ps -eo pid,ppid,stat,cmd | grep "Z"
```

**Check process cleanup:**
```bash
# Look for kill_process_tree calls
grep "kill_process_tree\|cleanup_zombies" artifacts/soak/soak_windows.log
```

### Root Cause Analysis

**Common causes:**
1. **subprocess.Popen without wait()** 
2. **TimeoutExpired not handled**
3. **Parent process not reaping children**

**Investigation:**
```python
# Find all subprocess calls
grep -rn "subprocess\|Popen" src/ tools/

# Check for missing wait() or communicate()
grep -A 5 "Popen" src/ tools/ | grep -v "wait\|communicate"
```

### Mitigation

**Immediate:**
```python
# Run cleanup script
python -c "from src.common.process_manager import cleanup_zombies; cleanup_zombies()"
```

**Prevention:**
1. **Always use process_manager:**
   ```python
   from src.common.process_manager import kill_process_tree
   
   try:
       proc = subprocess.Popen(...)
       proc.wait(timeout=30)
   except subprocess.TimeoutExpired:
       kill_process_tree(proc.pid, timeout=10)
   ```

2. **Use context managers:**
   ```python
   with subprocess.Popen(...) as proc:
       proc.wait()
   ```

---

## 6. High REST API Latency

### Symptoms
- REST calls taking > 500ms
- `latency_ms{stage="rest"}` metric high
- `http_pool_requests_waiting` > 0

### Diagnosis

**Check connection pool:**
```bash
# Look for pool saturation
grep "pool.*limit\|waiting for connection" artifacts/soak/soak_windows.log

# Check Prometheus metrics
# http_pool_requests_waiting > 0 = pool saturated
```

**Check network latency:**
```bash
# Test latency to Bybit
ping api.bybit.com
curl -w "@curl-format.txt" -o /dev/null -s https://api.bybit.com/v5/market/time
```

### Root Cause Analysis

**Common causes:**
1. **Connection pool too small** (requests blocked)
2. **DNS resolution slow** (cache miss)
3. **Network congestion** (ISP/routing issue)
4. **Exchange rate limiting** (429 responses)

**Investigation:**
```bash
# Check for rate limit responses
grep "429\|rate limit" artifacts/soak/soak_windows.log

# Check DNS cache hits
grep "DNS\|dns" artifacts/soak/soak_windows.log

# Measure actual latencies
grep "latency_ms" artifacts/soak/soak_windows.log | awk '{sum+=$2; count++} END {print sum/count}'
```

### Mitigation

**Immediate:**
```yaml
# Increase connection pool
connection_pool:
  limit: 150              # Increase from 100
  limit_per_host: 50      # Increase from 30
```

**Long-term:**
1. **Optimize request patterns:**
   - Batch requests where possible
   - Use WebSocket for real-time data (not REST)
   
2. **Add request caching:**
   ```python
   from functools import lru_cache
   
   @lru_cache(maxsize=128)
   async def get_symbol_info(self, symbol):
       # Cache symbol info for 5 minutes
       pass
   ```

3. **Monitor exchange status:**
   - Set up alerts for Bybit downtime/maintenance

---

## 7. Bot Crash or Hang

### Symptoms
- Process exits unexpectedly
- No logs being written
- Heartbeat stops (no `[HB] alive` messages)

### Diagnosis

**Check exit code:**
```bash
# In GitHub Actions
echo $?  # Non-zero = crash

# Check last log entries
tail -n 100 artifacts/soak/soak_windows.log
```

**Check for exceptions:**
```bash
# Find unhandled exceptions
grep -E "Traceback|Exception|Error" artifacts/soak/soak_windows.log | tail -n 50

# Check for OOM killer (Linux)
dmesg | grep -i "killed process"
```

### Root Cause Analysis

**Common causes:**
1. **Unhandled exception** in critical path
2. **Deadlock** in async code
3. **OOM killed** by system
4. **Infinite loop** (no progress)

**Investigation:**
```python
# Add comprehensive exception handling
try:
    await main_loop()
except Exception as e:
    log.critical(f"Fatal error: {e}", exc_info=True)
    # Emergency shutdown
    await cleanup()
    raise
```

### Mitigation

**Immediate:**
```bash
# Restart bot with more verbose logging
export LOG_LEVEL=DEBUG
python cli/run_bot.py
```

**Prevention:**
1. **Add watchdog:**
   ```python
   import asyncio
   from datetime import datetime
   
   class Watchdog:
       def __init__(self, timeout=300):
           self.timeout = timeout
           self.last_heartbeat = datetime.now()
       
       async def monitor(self):
           while True:
               await asyncio.sleep(60)
               if (datetime.now() - self.last_heartbeat).seconds > self.timeout:
                   log.error("Watchdog timeout! Bot appears hung.")
                   os._exit(1)  # Force exit
   ```

2. **Add health check endpoint:**
   ```python
   @app.get("/health")
   async def health():
       return {
           "status": "ok" if bot.is_running else "down",
           "last_heartbeat": bot.last_heartbeat_ts
       }
   ```

---

## 8. Security Vulnerabilities

### Symptoms
- Security audit CI fails
- `pip-audit` or `cargo audit` reports CVEs
- GitHub security alerts

### Diagnosis

**Run local audit:**
```bash
# Check Python dependencies
python tools/ci/security_audit.py

# Or directly
pip-audit --requirement requirements.txt

# Check Rust dependencies
cd rust && cargo audit
```

**Check severity:**
```bash
# Parse JSON output
cat pip-audit-report.json | jq '.vulnerabilities[] | {package, severity, id}'
```

### Mitigation

**Immediate:**
```bash
# For HIGH/CRITICAL issues, upgrade immediately
pip-audit --fix --requirement requirements.txt

# Review changes
git diff requirements.txt
```

**For false positives:**
```bash
# Add to pip-audit ignore list (use sparingly!)
pip-audit --ignore-vuln VULN-ID
```

**For Rust:**
```bash
# Update Cargo.lock
cd rust
cargo update
cargo audit

# If specific crate vulnerable, pin to safe version in Cargo.toml
```

---

## 🚨 Emergency Procedures

### Emergency Stop

**If soak test needs immediate abort:**

1. **Via GitHub Actions UI:**
   - Go to Actions → Running workflows
   - Click "Cancel workflow"

2. **Via self-hosted runner:**
   ```powershell
   # Find Python process
   tasklist | findstr python
   
   # Kill gracefully (allows shutdown)
   taskkill /PID <pid> /T
   
   # Force kill if hung (last resort)
   taskkill /F /PID <pid> /T
   ```

3. **Clean up resources:**
   ```bash
   # Cancel all orders on exchange
   python scripts/emergency_cancel_all.py
   
   # Stop background jobs
   Get-Job | Stop-Job
   Get-Job | Remove-Job
   ```

### Data Recovery

**If soak test crashes before artifact upload:**

```bash
# SSH to runner
ssh runner-host

# Manually archive artifacts
cd c:\Users\dimak\mm-bot\artifacts
tar -czf soak-artifacts-$(date +%Y%m%d-%H%M%S).tar.gz soak/

# Copy to safe location
scp soak-artifacts-*.tar.gz backup-server:/backups/
```

---

## 📞 Escalation Path

1. **Level 1: Automated Recovery**
   - Exponential backoff (WebSocket)
   - Log rotation
   - Resource monitoring alerts

2. **Level 2: Notification**
   - Telegram alert sent
   - Check GitHub Actions logs
   - Review artifacts

3. **Level 3: Manual Intervention**
   - Review this runbook
   - Apply specific mitigation
   - Restart if needed

4. **Level 4: Engineering Escalation**
   - Complex root cause analysis required
   - Code changes needed
   - Re-run after fixes

---

## 📊 Success Metrics

**Soak test is considered successful if:**

| Metric | Threshold | Status |
|--------|-----------|--------|
| Duration | ≥ 24 hours | ⏱ |
| Memory growth | < 10 MB/hour | 📈 |
| CPU usage (avg) | < 80% | 💻 |
| Disk usage | < 5 GB | 💾 |
| WS reconnections | < 10 per hour | 🔌 |
| Orphan orders | 0 | 📋 |
| Zombie processes | 0 | 👻 |
| Crashes | 0 | 💥 |
| Security issues | 0 CRITICAL/HIGH | 🔒 |

---

## 📚 Additional Resources

- **Pre-flight Checklist:** `SOAK_TEST_PREFLIGHT_CHECKLIST.md`
- **Task Summaries:** `TASK_XX_*_SUMMARY.md`
- **Architecture Audit:** `ARCHITECTURE_AUDIT_REPORT.md`
- **Bybit API Docs:** https://bybit-exchange.github.io/docs/
- **Prometheus Queries:** `monitoring/promql/`

---

**Last Reviewed:** 2025-10-01  
**Next Review:** After first successful 24h soak test  
**Maintainer:** DevOps/SRE Team

