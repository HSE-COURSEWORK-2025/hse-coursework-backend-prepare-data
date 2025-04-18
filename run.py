import argparse
import json
import requests
import time
import sys
import datetime
from settings import Settings


settings = Settings()


def load_user(user_json: str) -> dict:
    """Загружает объект пользователя из JSON-строки или файла."""
    try:
        with open(user_json, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, OSError):
        return json.loads(user_json)


def fetch_fresh_token(user: dict) -> str:
    """Запрос свежего access_token; при 401 возвращает None."""
    try:
        resp = requests.get(user["fresh_access_token_url"], headers={"Accept": "application/json"})
        if resp.status_code == 401:
            print(f"⚠️  Пропускаем {user['email']}: 401 Unauthorized", file=sys.stderr)
            return None
        resp.raise_for_status()
        return resp.json().get("access_token")
    except requests.RequestException as e:
        print(f"Ошибка при получении токена для {user['email']}: {e}", file=sys.stderr)
        return None


def fetch_fitness_data(token: str, data_type: str, start_ms: int, end_ms: int) -> dict:
    """POST к Google Fitness API для конкретного dataTypeName."""
    body = {
        "aggregateBy": [{"dataTypeName": data_type}],
        "bucketByTime": {"durationMillis": 24 * 60 * 60 * 1000},
        "startTimeMillis": start_ms,
        "endTimeMillis": end_ms
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    resp = requests.post(settings.GOOGLE_FITNESS_ENDPOINT, json=body, headers=headers)
    resp.raise_for_status()
    return resp.json()


def fetch_full_period(token: str, data_type: str, start_ms: int, end_ms: int):
    """Разбивает весь период на чанки и запрашивает каждый."""
    current_start = start_ms
    while current_start < end_ms:
        current_end = min(current_start + settings.CHUNK_DURATION_MS, end_ms)
        readable_start = datetime.datetime.fromtimestamp(current_start / 1000).strftime('%Y-%m-%d %H:%M:%S')
        readable_end = datetime.datetime.fromtimestamp(current_end / 1000).strftime('%Y-%m-%d %H:%M:%S')
        try:
            data = fetch_fitness_data(token, data_type, current_start, current_end)
            print(f"— {data_type} [{readable_start} - {readable_end}]: {len(data.get('bucket', []))} записей")
        except requests.HTTPError as e:
            print(f"Ошибка запроса {data_type} [{readable_start} - {readable_end}]: {e}", file=sys.stderr)
        current_start = current_end


def main():
    parser = argparse.ArgumentParser(
        description="Сбор всех Google Fitness данных для одного пользователя из JSON"
    )
    parser.add_argument(
        "--user-json", required=True,
        help="Путь к JSON-файлу с данными пользователя или JSON-строка"
    )
    args = parser.parse_args()

    user = load_user(args.user_json)
    token = fetch_fresh_token(user)
    if not token:
        sys.exit(1)

    start_ms = 0  # с 1 января 1970
    end_ms = int(time.time() * 1000)

    for scope in settings.SCOPES:
        for dt in settings.DATA_TYPES_BY_SCOPE.get(scope, []):
            fetch_full_period(token, dt, start_ms, end_ms)


if __name__ == "__main__":
    main()
