#!/usr/bin/env bash
# Прерываться при любой ошибке

echo "🔻 Останавливаем контейнеры"
docker compose down

echo "🗑️  Удаляем данные"
rm -rf docker_data

echo "📄 Проверяем .env"
if [ ! -f .env ]; then
    cat > .env <<EOF
AIRFLOW_UID=$(id -u)
CRON_SCHEDULE_CHANNEL_DATA_UPDATE="0 * * * *"
EOF
    echo "✅ Создан .env"
else
    echo "ℹ️  .env уже существует"
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
docker compose up airflow-init

echo "⚙️  Запускаем стек Airflow"
docker compose up --build

echo "🎉 Скрипт завершён"
