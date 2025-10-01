# 🎯 MM Rebate Bot: Action Items из аудита

**Дата создания:** 2025-10-01  
**Статус:** В работе  

---

## 🔥 КРИТИЧЕСКИЕ (исправить немедленно)

### SEC-001: API ключи в Docker Secrets
**Приоритет:** P0 (Критический)  
**Категория:** Безопасность  
**Время:** 2 часа  
**Файлы:** `docker-compose.yml`, `src/common/config.py`

**Текущее состояние:**
```yaml
# docker-compose.yml:9-17
environment:
  - BYBIT_API_KEY=${BYBIT_API_KEY}  # ❌ Plain text
  - BYBIT_API_SECRET=${BYBIT_API_SECRET}
```

**Требуемое изменение:**
```yaml
# docker-compose.yml
services:
  market-maker-bot:
    secrets:
      - bybit_api_key
      - bybit_api_secret
    environment:
      - BYBIT_API_KEY_FILE=/run/secrets/bybit_api_key
      - BYBIT_API_SECRET_FILE=/run/secrets/bybit_api_secret

secrets:
  bybit_api_key:
    external: true
  bybit_api_secret:
    external: true
```

**Изменения в коде:**
```python
# src/common/config.py - добавить функцию
def _load_secret(env_var: str) -> str:
    """Load secret from file if _FILE suffix exists, else from env."""
    file_var = f"{env_var}_FILE"
    if file_var in os.environ:
        with open(os.environ[file_var], 'r') as f:
            return f.read().strip()
    return os.getenv(env_var, '')

# Использовать:
config.bybit.api_key = _load_secret('BYBIT_API_KEY')
config.bybit.api_secret = _load_secret('BYBIT_API_SECRET')
```

**Команды для создания секретов:**
```bash
echo "your_api_key" | docker secret create bybit_api_key -
echo "your_api_secret" | docker secret create bybit_api_secret -
```

**Критерий завершения:**
- [ ] Docker Compose использует secrets
- [ ] Config.py читает из `/run/secrets/`
- [ ] Fallback на env vars для dev-режима
- [ ] Тесты проходят с mock секретами

---

### SOAK-001: Утечка памяти в lint_ascii_logs.py
**Приоритет:** P0 (Критический)  
**Категория:** Soak-стабильность  
**Время:** 1 час  
**Файл:** `tools/ci/lint_ascii_logs.py:22-25`

**Проблема:**
```python
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()  # ❌ Читает весь файл в память!
```

**Решение:**
```python
def check_file_ascii(path: str) -> List[Tuple[int, str]]:
    """Check file for non-ASCII content line-by-line."""
    violations = []
    max_line_length = 10000  # Safety limit
    
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line_no, line in enumerate(f, 1):
            # Safety: skip extremely long lines
            if len(line) > max_line_length:
                violations.append((line_no, 'line too long (>10KB)'))
                continue
            
            # Check only print() lines to reduce false positives
            if 'print(' in line:
                try:
                    line.encode('ascii')
                except UnicodeEncodeError as e:
                    snippet = line[max(0, e.start-20):e.end+20]
                    violations.append((line_no, f'non-ascii: {snippet!r}'))
    
    return violations

def main() -> int:
    violations = []
    for root, _, files in os.walk('.'):
        if any(seg in root for seg in ('/venv', '\\venv', '/dist', '\\dist', '/.git')):
            continue
        for fn in files:
            path = os.path.join(root, fn).lstrip('./')
            if not is_text_file(path):
                continue
            try:
                file_violations = check_file_ascii(path)
                violations.extend((path, ln, msg) for ln, msg in file_violations)
            except Exception as e:
                print(f'[WARN] Failed to check {path}: {e}', file=sys.stderr)
    
    if violations:
        for p, ln, msg in violations:
            print(f'ASCII_LINT {p}:{ln}: {msg}')
        return 2
    print('ASCII_LINT OK')
    return 0
```

**Критерий завершения:**
- [ ] Файлы читаются построчно
- [ ] Нет загрузки всего файла в память
- [ ] Добавлена защита от огромных строк
- [ ] Тест на файле 100MB проходит без OOM

---

### SOAK-002: Ротация логов в full_stack_validate.py
**Приоритет:** P0 (Критический)  
**Категория:** Soak-стабильность  
**Время:** 1 час  
**Файл:** `tools/ci/full_stack_validate.py:80-86`

**Проблема:** В 72-часовом soak-прогоне создается 500+ файлов логов.

**Решение:**
```python
# В начале файла
MAX_LOG_FILES_PER_STEP = 5
MAX_TOTAL_LOG_SIZE_MB = 500

def _cleanup_old_logs(label: str) -> None:
    """Keep only last N log files per step to prevent disk bloat."""
    # Get all log files for this step
    out_logs = sorted(
        CI_ARTIFACTS_DIR.glob(f"{label}.*.out.log"),
        key=lambda p: p.stat().st_mtime
    )
    err_logs = sorted(
        CI_ARTIFACTS_DIR.glob(f"{label}.*.err.log"),
        key=lambda p: p.stat().st_mtime
    )
    
    # Delete oldest files beyond limit
    for old_file in out_logs[:-MAX_LOG_FILES_PER_STEP]:
        try:
            old_file.unlink()
        except Exception:
            pass
    
    for old_file in err_logs[:-MAX_LOG_FILES_PER_STEP]:
        try:
            old_file.unlink()
        except Exception:
            pass

def _check_disk_space() -> None:
    """Alert if CI artifacts directory exceeds size limit."""
    total_size_mb = sum(
        f.stat().st_size for f in CI_ARTIFACTS_DIR.rglob('*') if f.is_file()
    ) / (1024 * 1024)
    
    if total_size_mb > MAX_TOTAL_LOG_SIZE_MB:
        print(f"[WARN] CI artifacts size: {total_size_mb:.1f} MB (limit: {MAX_TOTAL_LOG_SIZE_MB} MB)", 
              file=sys.stderr)
        # Aggressive cleanup: keep only last 2 per step
        for label in ['ascii_logs', 'json_writer', 'metrics_labels', 'tests_whitelist']:
            logs = sorted(CI_ARTIFACTS_DIR.glob(f"{label}.*.out.log"), key=lambda p: p.stat().st_mtime)
            for old_file in logs[:-2]:
                old_file.unlink(missing_ok=True)
                old_file.with_suffix('.err.log').unlink(missing_ok=True)

def run_step(label: str, cmd: List[str]) -> Dict[str, Any]:
    # В начале функции:
    _cleanup_old_logs(label)
    _check_disk_space()
    
    # ... rest of existing code ...
```

**Критерий завершения:**
- [ ] Хранится max 5 логов на каждый step
- [ ] Alert при превышении 500MB в `artifacts/ci/`
- [ ] Aggressive cleanup срабатывает автоматически
- [ ] 72-часовой тест не забивает диск

---

### NET-001: Exponential backoff в WebSocket reconnect
**Приоритет:** P0 (Критический)  
**Категория:** Надежность  
**Время:** 1 час  
**Файл:** `src/connectors/bybit_ws.py:483-512`

**Проблема:** Нет задержки между попытками переподключения.

**Решение:**
```python
import random

async def _handle_public_disconnect(self):
    """Handle public WebSocket disconnection with exponential backoff."""
    self.public_connected = False
    
    if self.public_ws:
        try:
            await self.public_ws.close()
        except Exception:
            pass
        self.public_ws = None
    
    self.reconnect_attempts += 1
    
    if self.reconnect_attempts > self.max_reconnect_attempts:
        logger.error(
            "Max reconnection attempts reached for public WebSocket",
            attempts=self.reconnect_attempts,
            max_attempts=self.max_reconnect_attempts
        )
        # Notify monitoring system
        if self.metrics:
            self.metrics.ws_reconnect_exhausted_total.labels(ws_type="public").inc()
        return
    
    # Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, max 60s
    backoff_base = 2 ** (self.reconnect_attempts - 1)
    backoff_sec = min(backoff_base, 60)
    
    # Add jitter (±30%) to prevent thundering herd
    jitter = random.uniform(-0.3 * backoff_sec, 0.3 * backoff_sec)
    sleep_sec = max(1.0, backoff_sec + jitter)
    
    logger.info(
        "Public WebSocket disconnected, will retry",
        attempt=self.reconnect_attempts,
        max_attempts=self.max_reconnect_attempts,
        backoff_sec=sleep_sec
    )
    
    await asyncio.sleep(sleep_sec)
    
    # Attempt reconnection
    try:
        await self._connect_public()
        self.reconnect_attempts = 0  # Reset on successful reconnect
        logger.info("Public WebSocket reconnected successfully")
    except Exception as e:
        logger.error("Failed to reconnect public WebSocket", error=str(e))
        # Will retry on next disconnect event

# То же самое для _handle_private_disconnect()
```

**Дополнительно добавить метрики:**
```python
# src/metrics/exporter.py
self.ws_reconnect_attempts_total = Counter(
    'ws_reconnect_attempts_total',
    'WebSocket reconnection attempts',
    ['ws_type']
)
self.ws_reconnect_exhausted_total = Counter(
    'ws_reconnect_exhausted_total',
    'WebSocket reconnection attempts exhausted',
    ['ws_type']
)
self.ws_reconnect_backoff_seconds = Histogram(
    'ws_reconnect_backoff_seconds',
    'WebSocket reconnection backoff duration',
    ['ws_type'],
    buckets=(1, 2, 4, 8, 16, 32, 60)
)
```

**Критерий завершения:**
- [ ] Exponential backoff реализован (1s → 60s)
- [ ] Jitter добавлен (±30%)
- [ ] Метрики экспортируются
- [ ] Тест: симуляция 10 разрывов, нет flood на биржу

---

### SYS-001: Graceful shutdown с очисткой ресурсов
**Приоритет:** P0 (Критический)  
**Категория:** Надежность  
**Время:** 1 час  
**Файл:** `cli/run_bot.py` (метод `stop()`)

**Решение:** Создать централизованный shutdown handler:

```python
# cli/run_bot.py
import signal
import asyncio
from typing import Optional, List

class MarketMakerBot:
    def __init__(self, ...):
        # ... existing init ...
        self._shutdown_event = asyncio.Event()
        self._background_tasks: List[asyncio.Task] = []
    
    def register_background_task(self, task: asyncio.Task, name: str) -> None:
        """Register background task for cleanup on shutdown."""
        task.set_name(name)
        self._background_tasks.append(task)
    
    async def stop(self, timeout: float = 30.0) -> None:
        """Graceful shutdown with resource cleanup."""
        logger.info("Initiating graceful shutdown...")
        self.running = False
        self._shutdown_event.set()
        
        start_time = time.time()
        
        # 1. Cancel all background tasks
        logger.info(f"Cancelling {len(self._background_tasks)} background tasks...")
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
        
        # Wait for cancellation with timeout
        if self._background_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._background_tasks, return_exceptions=True),
                    timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.warning("Some background tasks did not finish within timeout")
        
        # 2. Stop strategy (cancel orders)
        if self.strategy:
            try:
                logger.info("Stopping strategy and cancelling active orders...")
                await asyncio.wait_for(self.strategy.stop(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.error("Strategy stop timed out")
        
        # 3. Close WebSocket connections
        if self.ws_connector:
            try:
                logger.info("Closing WebSocket connections...")
                await asyncio.wait_for(self.ws_connector.disconnect(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.error("WebSocket disconnect timed out")
        
        # 4. Close REST session
        if self.rest_connector:
            try:
                logger.info("Closing REST session...")
                await asyncio.wait_for(
                    self.rest_connector.__aexit__(None, None, None),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.error("REST connector close timed out")
        
        # 5. Flush metrics
        if self.metrics:
            try:
                logger.info("Flushing metrics...")
                # Prometheus client doesn't need explicit flush, but log final state
                self.metrics.bot_uptime_seconds.set(time.time() - self.start_time)
            except Exception as e:
                logger.error(f"Failed to flush metrics: {e}")
        
        # 6. Close recorder
        if self.data_recorder:
            try:
                logger.info("Closing data recorder...")
                await asyncio.wait_for(self.data_recorder.close(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.error("Recorder close timed out")
        
        # 7. Save final snapshots
        try:
            logger.info("Saving final snapshots...")
            await asyncio.wait_for(self._save_all_snapshots(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error("Snapshot save timed out")
        
        # 8. Stop web server
        if self.web_runner:
            try:
                logger.info("Stopping web server...")
                await asyncio.wait_for(self.web_runner.cleanup(), timeout=3.0)
            except asyncio.TimeoutError:
                logger.error("Web server stop timed out")
        
        elapsed = time.time() - start_time
        logger.info(f"Shutdown complete in {elapsed:.2f}s")
    
    async def _save_all_snapshots(self) -> None:
        """Save all state snapshots atomically."""
        snapshots = [
            ('allocator', self._save_allocator_snapshot),
            ('throttle', self._save_throttle_snapshot),
            ('rollout', self._save_rollout_snapshot),
        ]
        
        for name, func in snapshots:
            try:
                await func()
                logger.debug(f"Saved {name} snapshot")
            except Exception as e:
                logger.error(f"Failed to save {name} snapshot: {e}")

# Signal handlers
def setup_signal_handlers(bot: MarketMakerBot):
    """Setup OS signal handlers for graceful shutdown."""
    loop = asyncio.get_event_loop()
    
    def handle_signal(signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        asyncio.create_task(bot.stop())
    
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    # Windows-specific
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, handle_signal)

# В main():
async def main():
    bot = MarketMakerBot(...)
    setup_signal_handlers(bot)
    
    try:
        await bot.initialize()
        await bot.start()
    except KeyboardInterrupt:
        pass
    finally:
        await bot.stop()
```

**Критерий завершения:**
- [ ] Все background tasks отменяются
- [ ] WebSocket/REST закрываются корректно
- [ ] Snapshots сохраняются атомарно
- [ ] Signal handlers обрабатывают SIGINT/SIGTERM
- [ ] Shutdown завершается за <30 секунд
- [ ] Тест: `kill -TERM <pid>` → graceful shutdown

---

## ⚠️ ВЫСОКИЕ (исправить в течение недели)

### SEC-002: Security scan в CI
**Приоритет:** P1 (Высокий)  
**Категория:** Безопасность  
**Время:** 1 час  

**Создать файл:** `.github/workflows/security.yml`

```yaml
name: Security Scan

on:
  push:
    branches: [main, develop]
  pull_request:
  schedule:
    - cron: '0 2 * * 1'  # Еженедельно по понедельникам

jobs:
  python-security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      
      - name: Install security tools
        run: |
          pip install pip-audit safety bandit
      
      - name: Pip audit
        run: pip-audit --requirement requirements.txt --format json --output pip-audit.json
        continue-on-error: true
      
      - name: Safety check
        run: safety check --file requirements.txt --json --output safety.json
        continue-on-error: true
      
      - name: Bandit static analysis
        run: bandit -r src/ -f json -o bandit.json
        continue-on-error: true
      
      - name: Upload security reports
        uses: actions/upload-artifact@v4
        with:
          name: security-reports-python
          path: |
            pip-audit.json
            safety.json
            bandit.json
      
      - name: Fail on critical vulnerabilities
        run: |
          if grep -q '"severity":"critical"' pip-audit.json safety.json bandit.json; then
            echo "❌ Critical vulnerabilities found!"
            exit 1
          fi
  
  rust-security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions-rs/toolchain@v1
        with:
          toolchain: stable
      
      - name: Install cargo-audit
        run: cargo install cargo-audit --locked
      
      - name: Cargo audit
        working-directory: rust
        run: cargo audit --json > ../cargo-audit.json
        continue-on-error: true
      
      - name: Upload cargo audit report
        uses: actions/upload-artifact@v4
        with:
          name: security-reports-rust
          path: cargo-audit.json
```

**Критерий завершения:**
- [ ] Security workflow добавлен в CI
- [ ] Запускается на каждый PR и commit в main
- [ ] Еженедельный scheduled run
- [ ] Fail на критических уязвимостях

---

### SEC-003: Обернуть логи через redact()
**Приоритет:** P1 (Высокий)  
**Категория:** Безопасность  
**Время:** 2 часа  

**Создать:** `src/common/logging.py`

```python
import logging
import sys
from typing import Any
from src.common.redact import redact, DEFAULT_PATTERNS

class SecureFormatter(logging.Formatter):
    """Log formatter that redacts sensitive data."""
    
    def format(self, record: logging.LogRecord) -> str:
        # Redact message
        if isinstance(record.msg, str):
            record.msg = redact(record.msg, DEFAULT_PATTERNS)
        
        # Redact args
        if record.args:
            record.args = tuple(
                redact(str(arg), DEFAULT_PATTERNS) if isinstance(arg, (str, bytes)) else arg
                for arg in record.args
            )
        
        # Redact exception info
        if record.exc_info and record.exc_info[1]:
            exc_str = str(record.exc_info[1])
            record.exc_text = redact(exc_str, DEFAULT_PATTERNS)
        
        return super().format(record)

def setup_secure_logging(level: str = "INFO"):
    """Setup secure logging with redaction."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(SecureFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    root_logger.addHandler(handler)
    
    return root_logger

# Replace all print() with logger
def secure_print(*args, **kwargs):
    """Secure replacement for print() that redacts secrets."""
    msg = ' '.join(str(arg) for arg in args)
    redacted = redact(msg, DEFAULT_PATTERNS)
    print(redacted, **kwargs)
```

**Заменить во всех файлах:**
```python
# ❌ Было:
print(f"Config: {config}")

# ✅ Стало:
logger.info("Config loaded", config=config.to_sanitized())
```

**Критерий завершения:**
- [ ] Все `print()` заменены на `logger.*`
- [ ] SecureFormatter применяется ко всем логам
- [ ] Тест: логирование конфига с API ключами → ключи редактированы

---

### PERF-001: Connection pooling в REST
**Приоритет:** P1 (Высокий)  
**Категория:** Производительность  
**Время:** 1 час  
**Файл:** `src/connectors/bybit_rest.py:103-106`

**Изменение:**
```python
async def __aenter__(self):
    """Async context manager entry with connection pooling."""
    connector = aiohttp.TCPConnector(
        limit=100,              # Max 100 connections total
        limit_per_host=20,      # Max 20 to Bybit API
        ttl_dns_cache=300,      # Cache DNS for 5 min
        force_close=False,      # Enable keep-alive
        enable_cleanup_closed=True,
    )
    
    timeout = aiohttp.ClientTimeout(
        total=30,       # Total request timeout
        connect=10,     # Connection timeout
        sock_read=20    # Socket read timeout
    )
    
    self.session = aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers={'Content-Type': 'application/json'},
        json_serialize=lambda obj: orjson.dumps(obj).decode(),  # Fast JSON
        raise_for_status=False  # Handle status manually
    )
    
    self.connected = True
    logger.info("REST connector initialized with connection pooling")
    return self
```

**Критерий завершения:**
- [ ] Connection pooling настроен
- [ ] Keep-alive включен
- [ ] DNS кеширование активно
- [ ] Benchmark: latency уменьшилась на 10-15%

---

### PERF-002: Заменить json на orjson везде
**Приоритет:** P1 (Высокий)  
**Категория:** Производительность  
**Время:** 2 часа  

**Создать:** `src/common/json_io.py`

```python
"""Centralized JSON I/O with orjson for performance."""
import orjson
from pathlib import Path
from typing import Any, Dict, Union

def dumps(obj: Any, *, pretty: bool = False) -> bytes:
    """Serialize to JSON bytes (fast)."""
    options = orjson.OPT_SORT_KEYS
    if pretty:
        options |= orjson.OPT_INDENT_2
    return orjson.dumps(obj, option=options)

def loads(data: Union[bytes, str]) -> Any:
    """Deserialize from JSON bytes or string (fast)."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return orjson.loads(data)

def load_file(path: Union[Path, str]) -> Dict[str, Any]:
    """Load JSON from file (fast)."""
    path = Path(path)
    return orjson.loads(path.read_bytes())

def save_file(obj: Any, path: Union[Path, str], *, pretty: bool = False) -> None:
    """Save JSON to file atomically (fast)."""
    path = Path(path)
    tmp = path.with_suffix('.tmp')
    
    options = orjson.OPT_SORT_KEYS
    if pretty:
        options |= orjson.OPT_INDENT_2
    
    tmp.write_bytes(orjson.dumps(obj, option=options) + b'\n')
    tmp.replace(path)
```

**Заменить во всех файлах:**
```python
# ❌ Было:
import json
data = json.loads(text)
json.dump(obj, f)

# ✅ Стало:
from src.common.json_io import loads, save_file
data = loads(text)
save_file(obj, path)
```

**Файлы для изменения:**
- `tools/soak/kpi_gate.py`
- `tools/rehearsal/pre_live_pack.py`
- `tools/ci/full_stack_validate.py`
- `src/common/artifacts.py`
- Все места с `json.loads()` / `json.dumps()`

**Критерий завершения:**
- [ ] Все `json.*` заменены на `orjson` (через обертку)
- [ ] Benchmark: JSON serialization на 3-5x быстрее
- [ ] Все тесты проходят

---

## 📝 СРЕДНИЕ (backlog на следующий спринт)

### ARCH-001: Разбить cli/run_bot.py на модули
**Приоритет:** P2 (Средний)  
**Категория:** Архитектура  
**Время:** 4 часа  

**Структура:**
```
cli/
├── run_bot.py              # Entry point (100 LOC)
├── bot/
│   ├── __init__.py
│   ├── core.py             # MarketMakerBot class (init, lifecycle)
│   ├── web_server.py       # HTTP endpoints
│   ├── admin_api.py        # Admin endpoints (/admin/*)
│   ├── snapshots.py        # State persistence
│   ├── hot_reload.py       # Config reload logic
│   └── background_tasks.py # Rebalance, scheduler watcher, etc.
```

**Критерий завершения:**
- [ ] run_bot.py < 200 строк
- [ ] Каждый модуль < 500 строк
- [ ] Все тесты проходят
- [ ] Import time не увеличился

---

### CONFIG-001: Разбить config.py на модули
**Приоритет:** P2 (Средний)  
**Категория:** Конфигурация  
**Время:** 3 часа  

**Структура:**
```
src/common/config/
├── __init__.py             # Public API
├── base.py                 # AppConfig, ConfigLoader
├── strategy.py             # StrategyConfig
├── risk.py                 # RiskConfig, GuardsConfig
├── portfolio.py            # PortfolioConfig, AllocatorConfig
├── monitoring.py           # MonitoringConfig
├── rollout.py              # RolloutConfig, RolloutRampConfig
├── validation.py           # validate_invariants, diff_runtime_safe
└── helpers.py              # cfg_hash_sanitized, get_git_sha
```

**Критерий завершения:**
- [ ] Каждый модуль < 300 строк
- [ ] Нет циклических импортов
- [ ] Все тесты проходят

---

### OBS-001: Prometheus Alert Rules
**Приоритет:** P2 (Средний)  
**Категория:** Наблюдаемость  
**Время:** 2 часа  

См. детальный отчет, раздел 7.1.2.

---

## 🔧 НИЗКИЕ (технический долг)

### RUST-001: Валидация в apply_snapshot()
**Приоритет:** P3 (Низкий)  
**Категория:** Rust  
**Время:** 1 час  

См. детальный отчет, раздел 1.3.

---

### RUST-002: Оптимизация reorder()
**Приоритет:** P3 (Низкий)  
**Категория:** Rust  
**Время:** 30 минут  

См. детальный отчет, раздел 2.3.1.

---

## 📊 Трекинг прогресса

### Статистика по приоритетам:

| Приоритет | Всего | Выполнено | В работе | Не начато |
|-----------|-------|-----------|----------|-----------|
| P0 (Критический) | 5 | 0 | 0 | 5 |
| P1 (Высокий) | 3 | 0 | 0 | 3 |
| P2 (Средний) | 3 | 0 | 0 | 3 |
| P3 (Низкий) | 2 | 0 | 0 | 2 |
| **ИТОГО** | **13** | **0** | **0** | **13** |

### Roadmap:

**Week 1 (текущая):**
- [ ] SEC-001, SOAK-001, SOAK-002, NET-001, SYS-001
- [ ] Milestone: Критические проблемы исправлены
- [ ] Deliverable: 24-часовой soak-тест пройден

**Week 2:**
- [ ] SEC-002, SEC-003, PERF-001, PERF-002
- [ ] Milestone: Высокие приоритеты закрыты
- [ ] Deliverable: 72-часовой soak-тест пройден

**Week 3:**
- [ ] ARCH-001, CONFIG-001, OBS-001
- [ ] Milestone: Средние приоритеты закрыты
- [ ] Deliverable: Production-ready release

**Week 4:**
- [ ] RUST-001, RUST-002
- [ ] Milestone: Технический долг сокращен
- [ ] Deliverable: v0.2.0 released

---

**Последнее обновление:** 2025-10-01  
**Следующий review:** 2025-10-08

