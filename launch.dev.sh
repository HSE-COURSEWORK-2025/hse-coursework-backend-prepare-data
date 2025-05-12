#!/usr/bin/env bash
# Прерываться при любой ошибке
set -euo pipefail

# Определяем IP адрес хоста
HOST_IP=$(hostname -I | awk '{print $1}')
if [ -z "$HOST_IP" ]; then
  echo "⚠️ Не удалось определить IP адрес хоста, ставим localhost"
  HOST_IP="127.0.0.1"
fi

echo "🔻 Останавливаем контейнеры"
docker compose down

echo "🗑️  Удаляем данные"
sudo rm -rf docker_data

echo "📄 Проверяем .env"
if [ ! -f .env ]; then
    cat > .env <<EOF
AIRFLOW_UID=1000
CRON_SCHEDULE_CHANNEL_DATA_UPDATE="0 * * * *"
# Устанавливаем дополнительные Python-пакеты для Airflow
_PIP_ADDITIONAL_REQUIREMENTS=python-dotenv
DATA_COLLECTION_API_BASE_URL="http://${HOST_IP}:8082"
AUTH_API_BASE_URL="http://${HOST_IP}:8081"
EOF
    echo "✅ Создан .env с URL на IP ${HOST_IP} и 설치 python-dotenv"
else
    echo "ℹ️  .env уже существует"
    # Обновляем или добавляем переменные URL и _PIP_ADDITIONAL_REQUIREMENTS
    declare -A vars=(
      [DATA_COLLECTION_API_BASE_URL]=8082
      [AUTH_API_BASE_URL]=8081
      [_PIP_ADDITIONAL_REQUIREMENTS]="python-dotenv"
    )
    for var in "${!vars[@]}"; do
        value=${vars[$var]}
        if [ "$var" = "_PIP_ADDITIONAL_REQUIREMENTS" ]; then
            new_value="$value"
        else
            new_value="http://${HOST_IP}:$value"
        fi
        if grep -qE "^${var}=" .env; then
            sed -i "s|^${var}=.*|${var}=${new_value}|" .env
            echo "🔄 Обновлён ${var} в .env: ${new_value}"
        else
            echo "${var}=${new_value}" >> .env
            echo "➕ Добавлен ${var} в .env: ${new_value}"
        fi
    done
fi

echo "🐳 Собираем образ для fetch_users"
DOCKER_BUILDKIT=1 docker build \
    --network=host \
    -f dockerfile.dag \
    -t fetch_users .

echo "🔒 Даём права на Docker socket"
# Меняем только конкретный файл — остальные файлы /var/run трогать не нужно
sudo chmod a+rw /var/run/docker.sock || true

echo "🌐 Проверяем сеть airflow_network"
if ! docker network ls --format '{{.Name}}' | grep -qw airflow_network; then
    docker network create airflow_network
    echo "✅ Сеть airflow_network создана"
else
    echo "ℹ️  Сеть airflow_network уже есть"
fi

echo "⚙️  Инициализируем Airflow"
sudo docker compose up airflow-init

echo "⚙️  Запускаем стек Airflow"
sudo docker compose up --build

echo "🎉 Скрипт завершён"
