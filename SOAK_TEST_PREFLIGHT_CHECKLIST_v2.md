# ✅ Soak Test - Pre-flight Checklist v2.0

**Дата создания:** 2025-10-02  
**Версия:** 2.0 (после полного ремонта)  
**Статус:** Production Ready

---

## 🎯 Цель

Убедиться, что все компоненты системы готовы к запуску 24-72 часового soak-теста.

---

## 📋 Checklist

### 🖥️ 1. Runner Infrastructure

- [ ] **Self-hosted Windows runner доступен**
  - Проверить: GitHub → Settings → Actions → Runners
  - Статус должен быть: `Idle` (зеленый)
  
- [ ] **Достаточно места на диске**
  - Минимум: **10 GB свободного места**
  - Проверка встроена в workflow (pre-flight check)
  
- [ ] **Runner не занят другими задачами**
  - Проверить очередь jobs в Actions
  - При необходимости использовать `concurrency` group

---

### 🔐 2. Секреты и учетные данные

- [ ] **API credentials настроены** (если используются)
  - `API_KEY` (опционально)
  - `API_SECRET` (опционально)
  - Проверить: Settings → Secrets and variables → Actions

- [ ] **Telegram notifications настроены** (опционально)
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
  - Проверить отправкой тестового сообщения

- [ ] **Proxy настроен** (если требуется)
  - `HTTP_PROXY`
  - `HTTPS_PROXY`

---

### 📦 3. Кодовая база

- [ ] **Все тесты проходят локально**
  - Запустить: `pytest tests/e2e/test_full_stack_validation.py`
  - Должно быть: 0 failures

- [ ] **CI pipeline зеленый**
  - Проверить последний commit в main/develop
  - Все checks должны быть passed

- [ ] **Нет известных критических багов**
  - Проверить issue tracker
  - Проверить последние PR

- [ ] **Код залит в репозиторий**
  - `git status` должен быть clean
  - Все изменения запушены

---

### 🛠️ 4. Workflow Configuration

- [ ] **Длительность теста выбрана**
  - `1` час - для проверки работоспособности
  - `24` часа - стандартный тест
  - `48-72` часа - перед major release

- [ ] **Переменные окружения корректны**
  ```yaml
  SOAK_ITERATION_TIMEOUT_SECONDS: "1200"  # 20 минут
  SOAK_HEARTBEAT_INTERVAL_SECONDS: "300"  # 5 минут
  FSV_MAX_LOGS_PER_STEP: "5"
  FSV_AGGRESSIVE_CLEANUP_MB: "750"
  ```

- [ ] **Schedule не конфликтует с другими задачами**
  - По умолчанию: каждый понедельник в 02:00 UTC
  - При необходимости изменить cron

---

### 🔧 5. Dependencies

- [ ] **Python 3.13 установлен на runner**
  - Проверка встроена в workflow (pre-flight check)

- [ ] **Rust toolchain установлен** (опционально)
  - Workflow сам установит при необходимости

- [ ] **Pip cache работает корректно**
  - Ключ: `${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}`
  - При изменении `requirements.txt` кэш обновится автоматически

- [ ] **Cargo cache работает корректно**
  - Ключ: `${{ runner.os }}-cargo-${{ hashFiles('rust/**/Cargo.lock', 'rust/**/Cargo.toml') }}`
  - При изменении Rust кода кэш обновится автоматически

---

### 📊 6. Monitoring & Logging

- [ ] **Resource monitor готов к работе**
  - Файл существует: `tools/soak/resource_monitor.py`
  - Проверка встроена в workflow (pre-flight check)

- [ ] **Log rotation включена**
  - Переменные `FSV_MAX_LOGS_PER_STEP`, `FSV_MAX_LOG_SIZE_MB`, `FSV_AGGRESSIVE_CLEANUP_MB` установлены
  - Механизм работает автоматически

- [ ] **Артефакты будут сохранены**
  - Retention: 14 дней (настроено в workflow)
  - Upload происходит всегда (`if: always()`)

---

### 🚨 7. Аварийные сценарии

- [ ] **Знаете, как остановить тест вручную**
  - GitHub Actions → Running job → Cancel workflow

- [ ] **Знаете, где смотреть логи**
  - GitHub Actions → Workflow run → Job logs
  - Real-time в браузере

- [ ] **Знаете, как интерпретировать сбой**
  - Смотреть последние 30 строк в логе
  - Скачать артефакты и проверить `.err.log`

- [ ] **План действий при сбое готов**
  1. Скачать артефакты
  2. Проанализировать `summary.txt` и `metrics.jsonl`
  3. Проверить `resources.analysis.json` на утечки памяти
  4. Исправить проблему
  5. Запустить snova

---

## 🔍 Pre-flight Automated Checks (встроены в workflow)

Workflow автоматически проверит:

✅ Python версия и доступность  
✅ Rust toolchain (опционально)  
✅ Критические файлы (`full_stack_validate.py`, `resource_monitor.py`)  
✅ Свободное место на диске (warning при <5GB)  

Если любая из проверок провалится, workflow упадет на шаге `Pre-flight checks`.

---

## 📝 Рекомендуемая процедура запуска

### Шаг 1: Проверка окружения
```bash
# На локальной машине
git pull origin main
pytest tests/e2e/test_full_stack_validation.py -v
```

### Шаг 2: Проверка CI
- Открыть GitHub Actions
- Проверить, что последний commit зеленый

### Шаг 3: Проверка runner
- Settings → Actions → Runners
- Убедиться, что runner Idle

### Шаг 4: Запуск
- Actions → "Soak (Windows self-hosted, 24-72h)"
- Run workflow
- Указать `soak_hours`
- Нажать "Run workflow"

### Шаг 5: Мониторинг
- Первые 5-10 минут: следить за логами
- Убедиться, что первая итерация прошла успешно
- Дальше можно проверять периодически

### Шаг 6: После завершения
- Скачать артефакты
- Проверить `metrics_summary.json`
- Проверить `resources.analysis.json`
- Сохранить результаты для трендового анализа

---

## ⚠️ Red Flags (когда НЕ запускать)

### ❌ НЕ запускать, если:

- **Runner offline** - тест не запустится
- **<5GB свободного места** - риск переполнения диска
- **Последний CI failed** - высокая вероятность немедленного сбоя
- **Известные критические баги** - тест упадет, потратив время runner
- **Другой soak-тест уже запущен** - конфликт ресурсов
- **Планируется deploy на runner** - тест будет прерван

### ⚠️ Запускать с осторожностью, если:

- **Недавние изменения в коде** - возможны неожиданные сбои
- **Новые зависимости добавлены** - проверить локально первым делом
- **Runner медленно работает** - timeout на итерацию может сработать
- **Много параллельных PR** - конфликты в коде

---

## 📈 Success Criteria

### Тест считается успешным, если:

✅ **100% итераций прошли успешно**
- `success_rate_percent: 100.0` в `metrics_summary.json`

✅ **Нет утечек памяти**
- `leak_detected: false` в `resources.analysis.json`
- `leak_mb_per_hour < 10` (менее 10MB/час)

✅ **Стабильная производительность**
- `max_duration` не более чем в 1.5 раза больше `avg_duration`
- Пример: avg=120s, max=180s - OK; avg=120s, max=300s - BAD

✅ **Нет "спайков" CPU/Memory**
- Проверить визуально в `resources.jsonl`

✅ **Логи без критических warnings**
- Нет `[ALERT]` в логах
- `[WARN]` допустимы, но требуют анализа

---

## 🎓 Lessons Learned (после ремонта)

### Что изменилось в v2.0:

1. **Fail-fast вместо retry**
   - Любая ошибка → немедленная остановка
   - Нет ложно-положительных результатов

2. **Timeout на итерацию**
   - Защита от зависаний
   - По умолчанию: 20 минут

3. **Автоматическая очистка**
   - Изоляция итераций
   - Защита от переполнения диска

4. **Structured metrics**
   - JSONL формат
   - Легко парсить и анализировать

5. **Pre-flight checks**
   - Автоматическая проверка окружения
   - Fail early

---

## 📞 Контакты при проблемах

- **Документация:** `SOAK_TEST_REPAIR_REPORT.md`
- **Quick Start:** `SOAK_TEST_QUICKSTART.md`
- **Workflow файл:** `.github/workflows/soak-windows.yml`
- **Валидационный скрипт:** `tools/ci/full_stack_validate.py`

---

## ✅ Final Check

Перед запуском задайте себе вопросы:

- [ ] Знаю ли я, зачем запускаю этот тест?
- [ ] Готов ли я анализировать результаты после завершения?
- [ ] Есть ли у меня план действий при сбое?
- [ ] Не помешает ли этот тест другим задачам?
- [ ] Проверил ли я все пункты checklist выше?

Если ответ "Да" на все вопросы - **готов к запуску! 🚀**

---

*Последнее обновление: 2025-10-02*  
*Версия: 2.0 (Production Ready)*

