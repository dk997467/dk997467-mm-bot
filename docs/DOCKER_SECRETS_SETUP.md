# 🔐 Docker Secrets Setup Guide

## Обзор

С версии 0.1.0+ MM Rebate Bot использует **Docker Secrets** для безопасного хранения API ключей и паролей. Это критическое улучшение безопасности, устраняющее риски утечки секретов через переменные окружения.

---

## 🎯 Преимущества Docker Secrets

✅ **Безопасность:**
- Секреты не видны в `docker inspect`
- Не хранятся в plain text в environment
- Не попадают в логи процессов (`/proc/<pid>/environ`)
- Шифруются в Docker Swarm

✅ **Совместимость:**
- Fallback на env vars для dev/test окружений
- Прозрачная миграция с существующих конфигураций

---

## 📋 Quick Start

### Production (Docker Swarm)

#### 1. Создайте секреты

```bash
# Создайте секреты из stdin
echo "your_real_api_key" | docker secret create bybit_api_key -
echo "your_real_api_secret" | docker secret create bybit_api_secret -
echo "your_postgres_password" | docker secret create postgres_password -
```

#### 2. Проверьте созданные секреты

```bash
docker secret ls
```

Вывод:
```
ID                          NAME                 CREATED         UPDATED
abc123def456                bybit_api_key        5 seconds ago   5 seconds ago
def456ghi789                bybit_api_secret     4 seconds ago   4 seconds ago
ghi789jkl012                postgres_password    3 seconds ago   3 seconds ago
```

#### 3. Запустите stack

```bash
docker stack deploy -c docker-compose.yml mm-bot
```

**Важно:** Docker Secrets работают только в Docker Swarm mode!

```bash
# Если еще не в swarm mode:
docker swarm init
```

---

### Development / Testing (без Docker Swarm)

Для локальной разработки используйте **file-based secrets** или **environment variables**.

#### Вариант A: File-based secrets (рекомендуется)

```bash
# Создайте директорию для секретов
mkdir -p ./secrets

# Создайте файлы секретов (НЕ коммитьте их в git!)
echo "test_api_key" > ./secrets/bybit_api_key
echo "test_api_secret" > ./secrets/bybit_api_secret
echo "test_password" > ./secrets/postgres_password

# Обновите docker-compose.yml для dev:
```

```yaml
# docker-compose.override.yml (для local dev)
version: '3.8'

services:
  market-maker-bot:
    secrets:
      - bybit_api_key
      - bybit_api_secret
      - postgres_password

secrets:
  bybit_api_key:
    file: ./secrets/bybit_api_key
  bybit_api_secret:
    file: ./secrets/bybit_api_secret
  postgres_password:
    file: ./secrets/postgres_password
```

Запуск:
```bash
docker-compose up
```

#### Вариант B: Environment variables (fallback)

Создайте `.env` файл:

```bash
# .env (НЕ коммитьте в git!)
BYBIT_API_KEY=your_test_key
BYBIT_API_SECRET=your_test_secret
STORAGE_PG_PASSWORD=test_password
```

Бот автоматически fallback на env vars, если секреты не найдены.

---

## 🔄 Как это работает

### Приоритет загрузки секретов

Функция `_load_secret()` в `src/common/config.py` проверяет в следующем порядке:

1. **`{VAR}_FILE` env var** → читает из файла
   ```python
   BYBIT_API_KEY_FILE=/run/secrets/bybit_api_key
   ```

2. **Docker Swarm secrets** → `/run/secrets/{var_name}`
   ```
   /run/secrets/bybit_api_key
   ```

3. **Environment variable** → классический способ
   ```python
   BYBIT_API_KEY=your_key
   ```

4. **Default value** → пустая строка или указанный default

### Пример логов

```
[INFO] Loaded BYBIT_API_KEY from Docker secret: /run/secrets/bybit_api_key
[INFO] Loaded BYBIT_API_SECRET from file: /run/secrets/bybit_api_secret
[INFO] Loaded STORAGE_PG_PASSWORD from environment variable
```

---

## 🛡️ Безопасность

### ✅ Do's (Хорошие практики)

1. **Production:** Всегда используйте Docker Secrets
2. **Rotation:** Регулярно обновляйте секреты
   ```bash
   docker secret rm bybit_api_key
   echo "new_key" | docker secret create bybit_api_key -
   docker service update --secret-rm bybit_api_key --secret-add bybit_api_key mm-bot_market-maker-bot
   ```

3. **Access Control:** Ограничьте доступ к секретам
   ```bash
   # Только specific service имеет доступ
   docker service create \
     --secret bybit_api_key \
     --name secure-service \
     myimage:latest
   ```

4. **Monitoring:** Отслеживайте доступ к секретам
   ```bash
   docker secret inspect bybit_api_key
   ```

### ❌ Don'ts (Анти-паттерны)

1. **НЕ коммитьте** секреты в git
   ```bash
   # Добавьте в .gitignore:
   secrets/
   .env
   *.secret
   ```

2. **НЕ логируйте** секреты
   ```python
   # ❌ ПЛОХО
   print(f"API Key: {api_key}")
   
   # ✅ ХОРОШО
   logger.info("API Key loaded successfully")
   ```

3. **НЕ используйте** env vars в production
   ```yaml
   # ❌ ПЛОХО (production)
   environment:
     - BYBIT_API_KEY=hardcoded_key
   
   # ✅ ХОРОШО
   secrets:
     - bybit_api_key
   ```

---

## 🔧 Troubleshooting

### Проблема: "Secret file not found"

**Симптом:**
```
[WARNING] Secret file not found: /run/secrets/bybit_api_key (from BYBIT_API_KEY_FILE)
```

**Решение:**
1. Убедитесь, что секрет создан:
   ```bash
   docker secret ls | grep bybit_api_key
   ```

2. Проверьте, что сервис имеет доступ:
   ```bash
   docker service inspect mm-bot_market-maker-bot --format '{{ .Spec.TaskTemplate.ContainerSpec.Secrets }}'
   ```

3. Перезапустите сервис:
   ```bash
   docker service update --force mm-bot_market-maker-bot
   ```

---

### Проблема: "No value found for BYBIT_API_KEY"

**Симптом:**
```
[WARNING] No value found for BYBIT_API_KEY (not in secrets or env)
```

**Решение:**

**Для Production:**
```bash
# Создайте секрет
echo "your_key" | docker secret create bybit_api_key -

# Добавьте к сервису
docker service update --secret-add bybit_api_key mm-bot_market-maker-bot
```

**Для Dev:**
```bash
# Вариант 1: Env var
export BYBIT_API_KEY="test_key"
docker-compose up

# Вариант 2: .env файл
echo "BYBIT_API_KEY=test_key" >> .env
docker-compose up
```

---

### Проблема: Секреты не обновляются

**Симптом:** После обновления секрета бот продолжает использовать старое значение.

**Решение:**

```bash
# 1. Удалите старый секрет из сервиса
docker service update --secret-rm bybit_api_key mm-bot_market-maker-bot

# 2. Удалите секрет
docker secret rm bybit_api_key

# 3. Создайте новый секрет
echo "new_key" | docker secret create bybit_api_key -

# 4. Добавьте к сервису
docker service update --secret-add bybit_api_key mm-bot_market-maker-bot

# 5. Форсируйте перезапуск
docker service update --force mm-bot_market-maker-bot
```

---

## 📊 Verification

### Проверка безопасности

```bash
# ✅ Секреты НЕ видны в environment
docker exec mm-bot-container env | grep BYBIT
# Должно показать только _FILE переменные

# ✅ Секреты доступны в контейнере
docker exec mm-bot-container cat /run/secrets/bybit_api_key
# Должен вернуть значение

# ✅ Процессы не видят plain text
docker exec mm-bot-container cat /proc/1/environ | grep BYBIT
# НЕ должно показать реальные ключи
```

---

## 🚀 Migration Guide

### Миграция с env vars на Docker Secrets

#### 1. Сохраните текущие ключи

```bash
# Извлеките из .env или docker-compose.yml
export OLD_API_KEY=$(grep BYBIT_API_KEY .env | cut -d'=' -f2)
export OLD_API_SECRET=$(grep BYBIT_API_SECRET .env | cut -d'=' -f2)
```

#### 2. Создайте Docker Secrets

```bash
echo "$OLD_API_KEY" | docker secret create bybit_api_key -
echo "$OLD_API_SECRET" | docker secret create bybit_api_secret -
```

#### 3. Обновите docker-compose.yml

Уже сделано! Текущий `docker-compose.yml` поддерживает оба способа.

#### 4. Удалите env vars из `.env`

```bash
# Закомментируйте или удалите
# BYBIT_API_KEY=...
# BYBIT_API_SECRET=...
```

#### 5. Перезапустите

```bash
docker stack deploy -c docker-compose.yml mm-bot
```

---

## 📚 Дополнительные ресурсы

- [Docker Secrets Documentation](https://docs.docker.com/engine/swarm/secrets/)
- [Security Best Practices](https://docs.docker.com/engine/security/)
- [Secrets in Compose](https://docs.docker.com/compose/use-secrets/)

---

## ✅ Checklist перед production

- [ ] Все секреты созданы через `docker secret create`
- [ ] `.env` файл НЕ содержит production ключей
- [ ] `secrets/` директория в `.gitignore`
- [ ] Docker Swarm mode активирован
- [ ] Логи не содержат plain text секретов
- [ ] Секреты ротируются регулярно (каждые 90 дней)
- [ ] Доступ к секретам ограничен (RBAC)

---

**Дата обновления:** 2025-10-01  
**Версия:** 1.0  
**Статус:** ✅ Production Ready

