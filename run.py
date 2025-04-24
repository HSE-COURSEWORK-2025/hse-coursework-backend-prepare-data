import asyncio
import argparse
import json
import requests
import sys
import datetime

from settings import Settings
from redis import redis_client
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import certifi

settings = Settings()

# === Настраиваем сессию с retry и актуальным CA ===
session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.verify = certifi.where()

# === Список всех типов данных в порядке SCOPES ===
all_data_types = []
for scope in settings.SCOPES or []:
    types = settings.DATA_TYPES_BY_SCOPE.get(scope, [])
    all_data_types.extend([dt for dt in types if dt.startswith("com.google")])

total_types = len(all_data_types)
# вес одной «части» прогресса
weight = 100.0 / total_types if total_types > 0 else 0.0


# UTC-конвертеры (без изменений)
def convert_milliseconds_to_utc(timestamp_ms):
    timestamp_sec = timestamp_ms / 1000.0
    dt = datetime.datetime.utcfromtimestamp(timestamp_sec)
    ms = int(timestamp_ms % 1000)
    return dt.strftime("%d %B %Y %H:%M:%S") + f".{ms:03d} UTC"


def convert_nanoseconds_to_utc(timestamp_ns):
    timestamp_sec = timestamp_ns / 1_000_000_000.0
    dt = datetime.datetime.utcfromtimestamp(timestamp_sec)
    nanosec = int(timestamp_ns % 1_000_000_000)
    micros = f"{nanosec:09d}"[:6]
    return dt.strftime("%d %B %Y %H:%M:%S") + f".{micros} UTC"


def load_user(user_json: str) -> dict:
    try:
        with open(user_json, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, OSError):
        return json.loads(user_json)


def fetch_fresh_token(user: dict) -> str:
    try:
        resp = requests.get(
            user["fresh_access_token_url"], headers={"Accept": "application/json"}
        )
        if resp.status_code == 401:
            print(f"⚠️ Пропускаем {user['email']}: 401 Unauthorized", file=sys.stderr)
            return None
        resp.raise_for_status()
        return resp.json().get("access_token")
    except requests.RequestException as e:
        print(f"Ошибка при получении токена для {user['email']}: {e}", file=sys.stderr)
        return None


def fetch_fitness_data(token: str, data_type: str, start_ms: int, end_ms: int) -> dict:
    body = {
        "aggregateBy": [{"dataTypeName": data_type}],
        "startTimeMillis": start_ms,
        "endTimeMillis": end_ms,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    resp = session.post(
        settings.GOOGLE_FITNESS_ENDPOINT, json=body, headers=headers, timeout=10
    )
    resp.raise_for_status()
    return resp.json()


async def fetch_full_period(
    token: str, data_type: str, start_ms: int, end_ms: int, email: str
):
    """
    Для одного data_type бежим по чанкам, считаем локальный прогресс,
    а из него — общий, и пушим общий прогресс в Redis.
    """
    # индекс и смещение для этого data_type
    try:
        idx = all_data_types.index(data_type)
    except ValueError:
        idx = 0
    offset = idx * weight

    total_duration = end_ms - start_ms
    current_start = start_ms

    while current_start < end_ms:
        current_end = min(current_start + settings.CHUNK_DURATION_MS, end_ms)

        # локальный прогресс текущего чанка: 0–100%
        try:
            data = fetch_fitness_data(token, data_type, current_start, current_end)
        except Exception as e:
            print(
                f"❌ Ошибка ({data_type}) [{current_start}-{current_end}]: {e}",
                file=sys.stderr,
            )
            return

        buckets = data.get("bucket", [])
        # если есть buckets — возьмём самый «поздний» на текущем чанке
        last_ts = None
        for b in buckets:
            st = b.get("startTimeMillis")
            if st is not None:
                last_ts = max(last_ts or 0, int(st))
        if last_ts is not None:
            local_pct = (last_ts - start_ms) / total_duration * 100
            # общий прогресс = offset + local_pct * weight/100
            overall = int(offset + (local_pct * weight / 100.0))
            overall = min(overall, 100)
            payload = json.dumps({"type": "google_fitness_api", "progress": overall})
            await redis_client.set(
                f"{settings.REDIS_DATA_COLLECTION_PROGRESS_BAR_NAMESPACE}{email}",
                payload,
            )
            print(f"[{data_type}] local {int(local_pct)}% → overall {overall}%")

        current_start = current_end

    # по завершению этого data_type уходим на его конец:
    final_overall = int(offset + weight)
    await redis_client.set(
        f"{settings.REDIS_DATA_COLLECTION_PROGRESS_BAR_NAMESPACE}{email}",
        json.dumps({"type": "google_fitness_api", "progress": min(final_overall, 100)}),
    )
    print(f"[{data_type}] done → overall {min(final_overall, 100)}%")


async def main():
    parser = argparse.ArgumentParser(
        description="Сбор всех Google Fitness данных для одного пользователя"
    )
    parser.add_argument(
        "--user-json",
        required=True,
        help="Путь к JSON-файлу или JSON-строка с данными пользователя",
    )
    await redis_client.connect()
    args = parser.parse_args()
    user = load_user(args.user_json)
    user_email = user.get("email")
    token = fetch_fresh_token(user)
    if not token:
        sys.exit(1)

    for scope in settings.SCOPES or []:
        for dt in settings.DATA_TYPES_BY_SCOPE.get(scope, []):
            await fetch_full_period(
                token, dt, settings.START_MS, settings.END_MS, user_email
            )


if __name__ == "__main__":
    asyncio.run(main())
