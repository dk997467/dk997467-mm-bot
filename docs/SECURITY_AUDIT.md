# Security Audit Guide

Автоматическая проверка зависимостей на известные уязвимости (CVE).

## 📋 Содержание

- [Обзор](#обзор)
- [CI/CD Integration](#cicd-integration)
- [Локальное использование](#локальное-использование)
- [Инструменты](#инструменты)
- [Политика безопасности](#политика-безопасности)
- [Исправление уязвимостей](#исправление-уязвимостей)

---

## Обзор

Проект использует два инструмента для security audit:

1. **`pip-audit`** - сканирует Python зависимости (requirements.txt)
2. **`cargo audit`** - сканирует Rust зависимости (Cargo.lock)

**Частота проверок:**
- ✅ При каждом push в main/develop
- ✅ При каждом pull request
- ✅ Еженедельно (понедельник 00:00 UTC)
- ✅ По требованию (workflow_dispatch)

**Политика fail:**
- 🔴 **CRITICAL** severity → ❌ Build fails
- 🟠 **HIGH** severity → ❌ Build fails
- 🟡 **MEDIUM** severity → ⚠️ Warning (build passes)
- 🟢 **LOW** severity → ℹ️ Info (build passes)

---

## CI/CD Integration

### GitHub Actions Workflow

Файл: `.github/workflows/security.yml`

**Jobs:**
1. `python-security` - Python dependencies audit
2. `rust-security` - Rust dependencies audit
3. `security-summary` - Aggregated summary

**Artifacts:**
- `python-security-audit/` - JSON и Markdown отчеты
- `rust-security-audit/` - JSON и text отчеты
- Retention: 90 дней

**Пример вывода:**

```
Python Dependencies Security Audit
===================================

### Python Security Audit Results

| Severity | Count |
|----------|-------|
| 🔴 CRITICAL | 0 |
| 🟠 HIGH | 0 |
| 🟡 MEDIUM | 2 |
| 🟢 LOW | 1 |

✅ No critical or high severity vulnerabilities found.
```

---

## Локальное использование

### Установка инструментов

**Python:**
```bash
pip install pip-audit
```

**Rust:**
```bash
cargo install cargo-audit --locked
```

### Запуск локального audit

**Через Python скрипт (рекомендуется):**

```bash
# Проверить всё (Python + Rust)
python tools/ci/security_audit.py

# Только Python
python tools/ci/security_audit.py --python

# Только Rust
python tools/ci/security_audit.py --rust

# Auto-fix Python vulnerabilities (upgrade packages)
python tools/ci/security_audit.py --python --fix
```

**Пример вывода:**

```
============================================================
Python Dependencies Security Audit
============================================================

⚙ Running pip-audit...

✗ Found 2 vulnerabilities:

  [MEDIUM] cryptography 41.0.0
    ID: GHSA-jfhm-5ghh-2f97
    Fix: Upgrade to 41.0.5, 42.0.0

  [LOW] urllib3 1.26.15
    ID: GHSA-g4mx-q9vg-27p4
    Fix: Upgrade to 1.26.18, 2.0.7

Summary by severity:
  MEDIUM: 1
  LOW: 1

============================================================
Security Audit Summary
============================================================

Python: ✓ PASS
Rust: ✓ PASS

✓ All security audits passed!
```

---

## Инструменты

### pip-audit

**Источники данных:**
- [OSV (Open Source Vulnerabilities)](https://osv.dev/)
- [PyPI Advisory Database](https://github.com/pypa/advisory-database)

**Основные команды:**

```bash
# Basic audit
pip-audit --requirement requirements.txt

# JSON output
pip-audit --requirement requirements.txt --format json

# Auto-fix (upgrade packages)
pip-audit --requirement requirements.txt --fix

# Specific vulnerability service
pip-audit --requirement requirements.txt --vulnerability-service osv

# Ignore specific CVEs
pip-audit --requirement requirements.txt --ignore-vuln GHSA-xxxx-xxxx-xxxx
```

**Дополнительные опции:**

```bash
# Check installed packages (instead of requirements.txt)
pip-audit

# Generate SBOM (Software Bill of Materials)
pip-audit --requirement requirements.txt --format cyclonedx-json

# Dry-run (check without modifying)
pip-audit --requirement requirements.txt --dry-run
```

### cargo audit

**Источники данных:**
- [RustSec Advisory Database](https://rustsec.org/)

**Основные команды:**

```bash
# Basic audit
cd rust/
cargo audit

# JSON output
cargo audit --json

# Ignore specific advisories
cargo audit --ignore RUSTSEC-2023-0001

# Update advisory database
cargo audit fetch
```

**Дополнительные опции:**

```bash
# Check for yanked crates
cargo audit --deny yanked

# Check for unmaintained crates
cargo audit --deny unmaintained

# Specific severity threshold
cargo audit --deny warnings
```

---

## Политика безопасности

### Severity Levels

| Severity | Action | Example |
|----------|--------|---------|
| **CRITICAL** | ❌ **Block deployment** | Remote code execution, arbitrary file access |
| **HIGH** | ❌ **Block deployment** | SQL injection, authentication bypass |
| **MEDIUM** | ⚠️ **Review & plan fix** | XSS, information disclosure |
| **LOW** | ℹ️ **Track & fix eventually** | Minor information leak, deprecated API |

### Exceptions

**Когда можно игнорировать уязвимости:**

1. **False positives** - уязвимость не применима к нашему use case
2. **No fix available** - нет патча, используем workaround
3. **Transitive dependency** - не используем уязвимую функциональность

**Процесс исключения:**

```bash
# Python: Ignore specific CVE
pip-audit --requirement requirements.txt --ignore-vuln GHSA-xxxx-xxxx-xxxx

# Rust: Ignore specific advisory
# В rust/Cargo.toml добавить:
[package.metadata.audit]
ignore = ["RUSTSEC-2023-0001"]
```

**Документировать исключения в:**
- `docs/SECURITY_EXCEPTIONS.md`
- Комментарий в PR с обоснованием
- Issue для отслеживания fix upstream

---

## Исправление уязвимостей

### Python

**Шаг 1: Идентифицировать уязвимую зависимость**

```bash
python tools/ci/security_audit.py --python
```

**Шаг 2: Проверить fix версию**

```
[HIGH] requests 2.28.0
  Fix: Upgrade to 2.31.0
```

**Шаг 3: Обновить requirements.txt**

```diff
- requests==2.28.0
+ requests>=2.31.0
```

**Шаг 4: Переустановить и протестировать**

```bash
pip install -r requirements.txt --upgrade
pytest tests/
```

**Шаг 5: Auto-fix (опционально)**

```bash
python tools/ci/security_audit.py --python --fix
```

**Шаг 6: Commit и push**

```bash
git add requirements.txt
git commit -m "security: upgrade requests to fix GHSA-xxxx-xxxx-xxxx"
git push
```

### Rust

**Шаг 1: Идентифицировать уязвимость**

```bash
cd rust/
cargo audit
```

**Шаг 2: Обновить Cargo.toml**

```diff
[dependencies]
- serde = "1.0.150"
+ serde = "1.0.193"
```

**Шаг 3: Обновить Cargo.lock**

```bash
cargo update -p serde
```

**Шаг 4: Тестировать**

```bash
cargo test
cargo build --release
```

**Шаг 5: Commit и push**

```bash
git add Cargo.toml Cargo.lock
git commit -m "security: upgrade serde to fix RUSTSEC-2024-xxxx"
git push
```

---

## Pre-commit Hook (опционально)

Автоматически запускать security audit перед commit.

**Создать `.git/hooks/pre-commit`:**

```bash
#!/bin/bash
# Pre-commit security audit

echo "Running security audit..."

python tools/ci/security_audit.py

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Security audit failed!"
    echo "   Fix vulnerabilities or use 'git commit --no-verify' to skip (NOT recommended)"
    exit 1
fi

echo "✅ Security audit passed"
```

**Сделать исполняемым:**

```bash
chmod +x .git/hooks/pre-commit
```

**Опционально: Skip при commit**

```bash
# Skip pre-commit hook (use only for non-security commits)
git commit --no-verify -m "docs: update README"
```

---

## Continuous Monitoring

### Dependabot (GitHub)

**Рекомендуется настроить Dependabot для автоматических PR:**

Файл: `.github/dependabot.yml`

```yaml
version: 2
updates:
  # Python dependencies
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10
    labels:
      - "dependencies"
      - "python"
    
  # Rust dependencies
  - package-ecosystem: "cargo"
    directory: "/rust"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10
    labels:
      - "dependencies"
      - "rust"
```

### Snyk / WhiteSource (опционально)

Интеграция с коммерческими SCA tools для более глубокого анализа.

---

## Troubleshooting

### pip-audit не находит уязвимости

**Проблема:** Старая база данных OSV

**Решение:**
```bash
pip install --upgrade pip-audit
pip-audit --cache-dir /tmp/pip-audit-cache
```

### cargo audit ошибка "advisory database not found"

**Проблема:** Не скачана advisory database

**Решение:**
```bash
cargo audit fetch
cargo audit
```

### False positives

**Проблема:** pip-audit сообщает о уязвимости, которая не применима

**Решение:**
1. Проверить CVE детали на https://osv.dev/
2. Если false positive, добавить в ignore list:
   ```bash
   pip-audit --ignore-vuln GHSA-xxxx-xxxx-xxxx
   ```
3. Документировать в `docs/SECURITY_EXCEPTIONS.md`

---

## FAQ

**Q: Как часто нужно запускать security audit?**

A: 
- В CI: автоматически при каждом push/PR
- Локально: перед каждым major commit
- Команда: минимум раз в неделю

**Q: Что делать если нет fix для уязвимости?**

A: 
1. Проверить issue tracker пакета
2. Рассмотреть альтернативные пакеты
3. Изолировать уязвимый код
4. Добавить WAF правила (если web-related)
5. Задокументировать в SECURITY_EXCEPTIONS.md

**Q: Можно ли автоматически обновлять зависимости?**

A:
- Python: `pip-audit --fix` (осторожно, может сломать API)
- Rust: `cargo update` (семантическое версионирование, безопаснее)
- Рекомендуем: Review каждое обновление manually

**Q: Как интегрировать в существующий CI/CD?**

A: Workflow `.github/workflows/security.yml` готов к использованию. Просто:
1. Commit файл в репозиторий
2. Push в main
3. Проверить результаты в Actions

---

## Resources

- [pip-audit documentation](https://pypi.org/project/pip-audit/)
- [cargo-audit documentation](https://docs.rs/cargo-audit/)
- [OSV Database](https://osv.dev/)
- [RustSec Advisory Database](https://rustsec.org/)
- [NIST NVD](https://nvd.nist.gov/)
- [OWASP Dependency Check](https://owasp.org/www-project-dependency-check/)

---

## Support

Вопросы и проблемы:
- GitHub Issues: https://github.com/YOUR_ORG/mm-bot/issues
- Security vulnerabilities: security@YOUR_ORG.com
- Documentation: docs/SECURITY_AUDIT.md (этот файл)

