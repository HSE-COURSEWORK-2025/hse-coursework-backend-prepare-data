import asyncio
import argparse
import json
import requests
import sys
import datetime
import certifi

from settings import Settings
from redis import redis_client
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from typing import Dict, Optional


FLOAT_TYPES = [
    "com.google.oxygen_saturation",
    "com.google.heart_rate.bpm",
    "com.google.height",
    "com.google.weight",
]
INT_TYPES = [
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
    "com.google.sleep.segment",
]

GOOGLE_TO_DATA_TYPE: Dict[str, str] = {
    # float-типы
    "com.google.oxygen_saturation":         "BloodOxygenData",
    "com.google.heart_rate.bpm":            "HeartRateRecord",
    "com.google.height":                    "HeightRecord",              # ← придумали
    "com.google.weight":                    "WeightRecord",

    # int-типы
    "com.google.activity.segment":          "ActivitySegmentRecord",     # ← придумали
    "com.google.activity.exercise":         "ExerciseSessionRecord",
    "com.google.calories.bmr":              "BasalMetabolicRateRecord",
    "com.google.calories.expended":         "TotalCaloriesBurnedRecord",
    "com.google.cycling.pedaling.cadence":  "CadenceRecord",             # ← придумали
    "com.google.cycling.pedaling.cumulative": "CumulativeCadenceRecord",  # ← придумали
    "com.google.heart_minutes":             "HeartMinutesRecord",        # ← придумали
    "com.google.active_minutes":            "ActiveMinutesRecord",       # ← придумали
    "com.google.power.sample":              "PowerRecord",
    "com.google.step_count.cadence":        "StepCadenceRecord",         # ← придумали
    "com.google.step_count.delta":          "StepsRecord",
    "com.google.sleep.segment":             "SleepSessionData",
}


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


def process_bucket_data(bucket: dict, data_type: str) -> list[dict]:
    """
    Разбор одного bucket: возвращает список распарсенных значений с метками времени.
    """
    results = []
    for dataset in bucket.get("dataset", []):
        for point in dataset.get("point", []):
            ts_ns = point.get("startTimeNanos")
            time_str = convert_nanoseconds_to_utc(int(ts_ns)) if ts_ns else ""
            values = point.get("value", [])
            if not values:
                continue
            val = values[0]
            if data_type in FLOAT_TYPES:
                v = val.get("fpVal")
            elif data_type in INT_TYPES:
                v = val.get("intVal")
            else:
                # Сохраняем весь payload для неизвестных типов
                fname = f"{data_type.replace('.', '_')}.json"
                with open(fname, "w", encoding="utf-8") as f:
                    json.dump(bucket, f, ensure_ascii=False, indent=2)
                print(f"Сырые данные сохранены в {fname}")
                return []
            if v is not None:
                results.append({"timestamp": time_str, "value": v})
    return results


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


def fetch_google_fitness_api_token(data: dict) -> str:
    try:
        resp = requests.get(
            data["google_fitness_api_token_url"], headers={"Accept": "application/json"}
        )
        if resp.status_code == 401:
            print(f"⚠️ Пропускаем {data['email']}: 401 Unauthorized", file=sys.stderr)
            return None
        resp.raise_for_status()
        return resp.json().get("access_token")
    except requests.RequestException as e:
        print(f"Ошибка при получении токена для {data['email']}: {e}", file=sys.stderr)
        return None


def fetch_access_token(data: dict) -> str:
    try:
        resp = requests.get(
            data["access_token_url"], headers={"Accept": "application/json"}
        )
        if resp.status_code == 401:
            print(f"⚠️ Пропускаем {data['email']}: 401 Unauthorized", file=sys.stderr)
            return None
        resp.raise_for_status()
        return resp.json().get("access_token")
    except requests.RequestException as e:
        print(f"Ошибка при получении токена для {data['email']}: {e}", file=sys.stderr)
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
    google_fitness_api_token: str, access_token: str, data_type: str, start_ms: int, end_ms: int, email: str
):
    """
    Для одного data_type бежим по чанкам, считаем прогресс,
    парсим данные и отправляем их на внешний сервис.
    """
    try:
        idx = all_data_types.index(data_type)
    except ValueError:
        idx = 0
    offset = idx * weight
    total_duration = end_ms - start_ms
    current_start = start_ms

    while current_start < end_ms:
        current_end = min(current_start + settings.CHUNK_DURATION_MS, end_ms)

        # запрос в Google Fitness API
        try:
            payload = fetch_fitness_data(google_fitness_api_token, data_type, current_start, current_end)
        except Exception as e:
            print(f"❌ Ошибка ({data_type}) [{current_start}-{current_end}]: {e}", file=sys.stderr)
            return

        # обновляем прогресс
        buckets = payload.get("bucket", [])
        last_ts = max((int(b.get("startTimeMillis", 0)) for b in buckets), default=None)
        if last_ts:
            local_pct = (last_ts - start_ms) / total_duration * 100
            overall = min(int(offset + (local_pct * weight / 100.0)), 100)
            bar = json.dumps({"type": "google_fitness_api", "progress": overall})
            await redis_client.set(
                f"{settings.REDIS_DATA_COLLECTION_GOOGLE_FITNESS_API_PROGRESS_BAR_NAMESPACE}{email}",
                bar
            )
            print(f"[{data_type}] local {int(local_pct)}% → overall {overall}%")

        # парсим каждый bucket и отправляем
        for bucket in buckets:
            processed = process_bucket_data(bucket, data_type)
            if not processed:
                continue

            # POST на внешний сервис
            if not GOOGLE_TO_DATA_TYPE.get(data_type):
                continue
            
            url_data_type = GOOGLE_TO_DATA_TYPE.get(data_type)
            url = f"{settings.DATA_COLLECTION_API_BASE_URL}/data-collection-api/api/v1/post_data/raw_data_google_fitness_api/{url_data_type}"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            }

            try:
                resp = requests.post(
                    url,
                    json=processed,
                    headers=headers,
                    timeout=5
                )
                resp.raise_for_status()
                print(f"→ Отправлено {len(processed)} записей {data_type} на {url}")
            except Exception as e:
                print(f"❌ Ошибка отправки {data_type} на {url}: {e}", file=sys.stderr)

        current_start = current_end

    # финальный прогресс
    final_overall = min(int(offset + weight), 100)
    await redis_client.set(
        f"{settings.REDIS_DATA_COLLECTION_GOOGLE_FITNESS_API_PROGRESS_BAR_NAMESPACE}{email}",
        json.dumps({"type": "google_fitness_api", "progress": final_overall})
    )
    print(f"[{data_type}] done → overall {final_overall}%")


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
    google_fitness_api_token = fetch_google_fitness_api_token(user)
    access_token = fetch_access_token(user)
    if not google_fitness_api_token:
        sys.exit(1)

    if not access_token:
        sys.exit(1)

    for scope in settings.SCOPES or []:
        for dt in settings.DATA_TYPES_BY_SCOPE.get(scope, []):
            await fetch_full_period(
                google_fitness_api_token, access_token, dt, settings.START_MS, settings.END_MS, user_email
            )


if __name__ == "__main__":
    asyncio.run(main())
