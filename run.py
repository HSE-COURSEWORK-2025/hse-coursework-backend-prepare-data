import asyncio
import argparse
import json
import requests
import time
import sys
import datetime
from settings import Settings
from redis import redis_client


settings = Settings()


def convert_milliseconds_to_utc(timestamp_ms):
    # Переводим миллисекунды в секунды (с дробной частью)
    timestamp_sec = timestamp_ms / 1000.0
    dt = datetime.datetime.utcfromtimestamp(timestamp_sec)
    milliseconds = int(timestamp_ms % 1000)
    return dt.strftime("%d %B %Y %H:%M:%S") + f".{milliseconds:03d}" + " UTC"


def convert_nanoseconds_to_utc(timestamp_ns):
    # Переводим наносекунды в секунды (с дробной частью)
    timestamp_sec = timestamp_ns / 1_000_000_000.0
    dt = datetime.datetime.utcfromtimestamp(timestamp_sec)
    nanoseconds = int(timestamp_ns % 1_000_000_000)
    # первые 6 цифр → микросекунды
    micros_str = f"{nanoseconds:09d}"[:6]
    return dt.strftime("%d %B %Y %H:%M:%S") + f".{micros_str}" + " UTC"


def load_user(user_json: str) -> dict:
    """Загружает объект пользователя из JSON-строки или файла."""
    try:
        with open(user_json, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, OSError):
        return json.loads(user_json)


def fetch_fresh_token(user: dict) -> str:
    """Запрос свежего access_token; при 401 возвращает None."""
    try:
        resp = requests.get(
            user["fresh_access_token_url"], headers={"Accept": "application/json"}
        )
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
        "startTimeMillis": start_ms,
        "endTimeMillis": end_ms,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    resp = requests.post(settings.GOOGLE_FITNESS_ENDPOINT, json=body, headers=headers)
    resp.raise_for_status()
    return resp.json()


async def fetch_full_period(
    token: str, data_type: str, start_ms: int, end_ms: int, email: str
):
    """Разбивает весь период на чанки и запрашивает каждый."""
    total_duration = end_ms - start_ms
    current_start = start_ms

    while current_start < end_ms:
        current_end = min(current_start + settings.CHUNK_DURATION_MS, end_ms)
        readable_start = datetime.datetime.fromtimestamp(current_start / 1000).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        readable_end = datetime.datetime.fromtimestamp(current_end / 1000).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        try:
            data = fetch_fitness_data(token, data_type, current_start, current_end)
            buckets = data.get("bucket", [])

            for bucket in buckets:
                bucketStartTimeMillis = bucket.get("startTimeMillis")
                if bucketStartTimeMillis:
                    progress = (int(bucketStartTimeMillis) - start_ms) / total_duration
                    progress = str(int(progress * 100))
                    print(f"progress: {progress}")
                    payload = json.dumps(
                        {"type": "progress", "health": progress, "fitness": progress}
                    )
                    await redis_client.set(
                        f"{settings.REDIS_DATA_COLLECTION_PROGRESS_BAR_NAMESPACE}{email}",
                        payload,
                    )

                for dataset in bucket.get("dataset", []):
                    for point in dataset.get("point", []):
                        point_time_nanos = int(point.get("startTimeNanos"))
                        point_time = convert_nanoseconds_to_utc(point_time_nanos)
                        point_time_ms = point_time_nanos / 1_000_000.0
                        progress = (point_time_ms - start_ms) / total_duration
                        progress = str(int(progress * 100))
                        payload = json.dumps(
                            {
                                "type": "progress",
                                "health": progress,
                                "fitness": progress,
                            }
                        )
                        await redis_client.set(
                            f"{settings.REDIS_DATA_COLLECTION_PROGRESS_BAR_NAMESPACE}{email}",
                            payload,
                        )

                        print(f"progress: {progress}")

                        values = point.get("value", [])
                        if not values:
                            continue

                        # Две категории данных: float и int
                        if data_type in [
                            "com.google.oxygen_saturation",
                            "com.google.heart_rate.bpm",
                        ]:
                            point_value = values[0].get("fpVal")
                            if point_value is not None:
                                pass
                                # print(f"{point_value} at {point_time} – progress: {progress:.6f}")
                        else:
                            point_value = values[0].get("intVal")
                            if point_value is not None:
                                end_readable = convert_milliseconds_to_utc(end_ms)
                                # print(f"{point_value} at {point_time} – out of {end_readable} – progress: {progress:.6f}")

        except requests.HTTPError as e:
            print(
                f"Ошибка запроса {data_type} [{readable_start} - {readable_end}]: {e}",
                file=sys.stderr,
            )

        current_start = current_end

    progress = 100
    payload = json.dumps(
        {
            "type": "progress",
            "health": progress,
            "fitness": progress,
        }
    )
    await redis_client.set(
        f"{settings.REDIS_DATA_COLLECTION_PROGRESS_BAR_NAMESPACE}{email}",
        payload,
    )


async def main():
    parser = argparse.ArgumentParser(
        description="Сбор всех Google Fitness данных для одного пользователя из JSON"
    )
    parser.add_argument(
        "--user-json",
        required=True,
        help="Путь к JSON-файлу с данными пользователя или JSON-строка",
    )

    await redis_client.connect()

    args = parser.parse_args()

    user = load_user(args.user_json)
    user_email = user.get("email")
    token = fetch_fresh_token(user)
    if not token:
        sys.exit(1)

    for scope in settings.SCOPES:
        for dt in settings.DATA_TYPES_BY_SCOPE.get(scope, []):
            await fetch_full_period(
                token, dt, settings.START_MS, settings.END_MS, user_email
            )


if __name__ == "__main__":
    asyncio.run(main())
