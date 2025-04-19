import argparse
import json
import requests
import time
import sys
import datetime
from settings import Settings


settings = Settings()


def convert_nanoseconds_to_utc(timestamp_ns):
    # Переводим наносекунды в секунды (с дробной частью)
    timestamp_sec = timestamp_ns / 1_000_000_000.0
    
    # Создаём datetime объект
    dt = datetime.datetime.utcfromtimestamp(timestamp_sec)
    
    # Извлекаем наносекунды из исходного значения
    nanoseconds = int(timestamp_ns % 1_000_000_000)
    
    # Форматируем дату с наносекундами (первые 6 цифр → микросекунды)
    return dt.strftime("%d %B %Y %H:%M:%S") + f".{nanoseconds:09d}"[:10] + " UTC"


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
        # "bucketByTime": {"durationMillis": 24 * 60 * 60 * 1000},
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
            
            if data_type in ['com.google.oxygen_saturation', 'com.google.heart_rate.bpm']:
                buckets = data.get('bucket', [])
                for bucket in buckets:
                    dataset = bucket.get('dataset', [])
                    for data in dataset:
                        points = data.get('point', [])
                        for point in points:
                            point_time_nanos = point.get('startTimeNanos')
                            point_time = convert_nanoseconds_to_utc(int(point_time_nanos))
                            point_value = None
                            values = point.get('value', [])
                            if values:
                                point_value = values[0].get('fpVal')
                                print(point_value, point_time)
            
            
            elif data_type in [
            "com.google.activity.segment",
            "com.google.calories.bmr",
            "com.google.calories.expended",
            "com.google.cycling.pedaling.cadence",
            "com.google.cycling.pedaling.cumulative",
            "com.google.heart_minutes",
            "com.google.active_minutes",
            "com.google.power.sample",
            "com.google.step_count.cadence",
            "com.google.step_count.delta",
            "com.google.activity.exercise",
            "com.google.sleep.segment"
        ]:
                buckets = data.get('bucket', [])
                for bucket in buckets:
                    dataset = bucket.get('dataset', [])
                    for data in dataset:
                        points = data.get('point', [])
                        for point in points:
                            point_time_nanos = point.get('startTimeNanos')
                            point_time = convert_nanoseconds_to_utc(int(point_time_nanos))
                            point_value = None
                            values = point.get('value', [])
                            if values:
                                point_value = values[0].get('intVal')
                                if point_value:
                                    print(point_value, point_time)
                

            else:
                
                with open('testek2.json', 'w') as f:
                    f.write(str(data))
                    
            # print(f"— {data_type} [{readable_start} - {readable_end}]: {len(data.get('bucket', []))} записей")
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

    start_ms = int((time.time() - 14 * 24 * 60 * 60) * 1000)
    end_ms = int(time.time() * 1000)

    for scope in settings.SCOPES:
        for dt in settings.DATA_TYPES_BY_SCOPE.get(scope, []):
            fetch_full_period(token, dt, start_ms, end_ms)


if __name__ == "__main__":
    main()
