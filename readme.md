# HSE Coursework: Data Preprocessing Backend

Этот репозиторий содержит процесс для агрегации и предобработки пользовательских данных, поступающих из различных источников, с последующим сохранением результатов в базе данных.

## Основные возможности
- Агрегация и предобработка данных по различным типам активности (шаги, калории, сон и др.)
- Сохранение агрегированных данных в базе данных
- Отправка уведомлений о начале и завершении этапа предобработки


## Быстрый старт

### 1. Клонирование репозитория
```bash
git clone https://github.com/your-username/hse-coursework-backend-prepare-data.git
cd hse-coursework-backend-prepare-data
```

### 2. Сборка Docker-образа
```bash
docker build -f dockerfile.dag -t preprocess_data:latest .
```

### 3. Запуск контейнера
```bash
docker run --env-file .env.prod preprocess_data:latest --email <user@example.com>
```
Где `<user@example.com>` — email пользователя, для которого требуется выполнить агрегацию и предобработку данных.

### 4. Переменные окружения
Используйте `.env.dev` для разработки и `.env.prod` для продакшена. Примеры переменных:
```
DATA_COLLECTION_API_BASE_URL=http://localhost:8082
AUTH_API_BASE_URL=http://localhost:8081
REDIS_HOST=localhost
NOTIFICATIONS_API_BASE_URL=http://localhost:8083/notifications-api/api/v1/notifications
```

### 5. Развёртывание в Kubernetes
Скрипт для развертывания:
```bash
./deploy.sh
```

## Структура проекта
- `run.py` — основной скрипт запуска процесса агрегации и предобработки
- `records_db/` — модуль для работы с базой данных (engine, сессии, схемы)
- `notifications.py` — отправка email-уведомлений
- `settings.py` — конфигурация приложения
- `requirements.txt` — зависимости Python
- `dockerfile.dag` — Dockerfile для сборки образа
- `deploy.sh` — скрипт для деплоя в Kubernetes

## Пример запуска
```bash
docker run --env-file .env.prod preprocess_data:latest --email user@example.com
```
