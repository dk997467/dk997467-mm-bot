# 🔐 Migration to Docker Secrets - Quick Guide

## Что изменилось?

**Версия 0.1.0+** внесла критическое улучшение безопасности: API ключи теперь загружаются из **Docker Secrets** вместо переменных окружения.

---

## ⚡ Quick Migration (5 минут)

### Production (Docker Swarm)

```bash
# 1. Init swarm (если еще не в swarm mode)
docker swarm init

# 2. Создайте секреты
echo "your_real_api_key" | docker secret create bybit_api_key -
echo "your_real_api_secret" | docker secret create bybit_api_secret -
echo "your_postgres_password" | docker secret create postgres_password -

# 3. Deploy
docker stack deploy -c docker-compose.yml mm-bot

# 4. Проверка
docker service logs mm-bot_market-maker-bot | grep "Loaded.*from Docker secret"
```

**Готово!** Ваши секреты теперь безопасны.

---

### Development (Docker Compose)

```bash
# 1. Создайте директорию для секретов
mkdir -p ./secrets

# 2. Создайте файлы секретов
echo "test_api_key" > ./secrets/bybit_api_key
echo "test_api_secret" > ./secrets/bybit_api_secret
echo "test_password" > ./secrets/postgres_password

# 3. Скопируйте example override
cp docker-compose.override.yml.example docker-compose.override.yml

# 4. Запустите
docker-compose up
```

---

## 🔍 Проверка работы

### Логи должны показать:

```
[INFO] Loaded BYBIT_API_KEY from Docker secret: /run/secrets/bybit_api_key
[INFO] Loaded BYBIT_API_SECRET from Docker secret: /run/secrets/bybit_api_secret
[INFO] Configuration loaded successfully
```

### Секреты НЕ видны в environment:

```bash
# ✅ Правильно: только _FILE переменные
docker exec mm-bot-container env | grep BYBIT
BYBIT_API_KEY_FILE=/run/secrets/bybit_api_key
BYBIT_API_SECRET_FILE=/run/secrets/bybit_api_secret

# ❌ Плохо: не должно быть plain text
docker exec mm-bot-container env | grep BYBIT
BYBIT_API_KEY=your_actual_key  # ← Так больше НЕ должно быть!
```

---

## 🚨 Что делать, если что-то не работает?

### Ошибка: "No value found for BYBIT_API_KEY"

**Причина:** Секреты не созданы или недоступны.

**Решение (Production):**
```bash
docker secret ls  # Проверьте, что секреты созданы
docker service update --secret-add bybit_api_key mm-bot_market-maker-bot
```

**Решение (Dev):**
```bash
# Используйте env var fallback
export BYBIT_API_KEY="test_key"
export BYBIT_API_SECRET="test_secret"
docker-compose up
```

---

### Ошибка: "Secret file not found"

**Причина:** Неправильный путь к файлу секрета.

**Решение:**
```bash
# Проверьте, что файл существует
docker exec mm-bot-container ls -la /run/secrets/

# Должен быть вывод:
# -r--r--r-- 1 root root 32 Oct 1 12:00 bybit_api_key
# -r--r--r-- 1 root root 64 Oct 1 12:00 bybit_api_secret
```

---

## 📚 Полная документация

Для детальных инструкций см. **[docs/DOCKER_SECRETS_SETUP.md](docs/DOCKER_SECRETS_SETUP.md)**

---

## ✅ Checklist

- [ ] Docker Swarm mode активирован (production)
- [ ] Секреты созданы через `docker secret create`
- [ ] Сервис перезапущен
- [ ] Логи показывают "Loaded from Docker secret"
- [ ] `docker exec ... env` НЕ показывает plain text ключей
- [ ] `.env` файл не содержит production секретов
- [ ] `secrets/` директория в `.gitignore`

---

**Время миграции:** 5-10 минут  
**Сложность:** ⭐☆☆☆☆ (Легко)  
**Impact:** 🔒 Критическое улучшение безопасности

Вопросы? См. [docs/DOCKER_SECRETS_SETUP.md](docs/DOCKER_SECRETS_SETUP.md)

