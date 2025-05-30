import asyncio
import argparse
import logging
import re
import sys
from datetime import datetime
import random

from sqlalchemy.future import select
from sqlalchemy import func

from notifications import notifications_api
from db.schemas import MLPredictionsRecords, RawRecords
from db.db_session import get_session
from settings import Settings

# Настройки
settings = Settings()
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

async def store_predictions(session, email: str, iteration: int):
    now = datetime.utcnow()
    diagnoses = [
        ("Insomnia Risk", random.random()),
        ("Arrhythmia Risk", random.random())
    ]
    records = []

    for name, prob in diagnoses:
        rec = MLPredictionsRecords(
            email=email,
            result_value=str(prob),
            diagnosis_name=name,
            iteration_num=iteration,
            iteration_datetime=now
        )
        records.append(rec)
        logger.info(f"Generated {name}: {prob:.4f}")

    session.add_all(records)
    session.commit()
    logger.info(f"Committed {len(records)} ML predictions to DB")

async def main(email: str):
    # Определяем итерацию
    session = await get_session().__anext__()
    result = session.execute(
        select(func.max(MLPredictionsRecords.iteration_num))
        .where(MLPredictionsRecords.email == email)
    )
    max_iter = result.scalar() or 0
    iteration_number = max_iter + 1

    start_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    subject_start = f"[ML Iteration #{iteration_number}] Запуск ML-анализа"
    body_start = f"""
    <html>
      <body>
        <h2>🚀 ML Анализ — Запуск итерации #{iteration_number}</h2>
        <p><strong>Пользователь:</strong> {email}</p>
        <p><strong>Время старта:</strong> {start_time}</p>
        <p>Начинаем генерацию прогноза рисков.</p>
      </body>
    </html>
    """
    await notifications_api.send_email(email, subject_start, body_start)
    logger.info("Sent ML start notification email")

    # Генерируем и сохраняем прогнозы
    await store_predictions(session, email, iteration_number)


    finish_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    subject_end = f"[ML Iteration #{iteration_number}] Завершение ML-анализа"
    body_end = f"""
    <html>
      <body>
        <h2>✅ ML Анализ — Итерация #{iteration_number} завершена</h2>
        <p><strong>Пользователь:</strong> {email}</p>
        <p><strong>Время старта:</strong> {start_time}</p>
        <p><strong>Время окончания:</strong> {finish_time}</p>
        <p>Прогнозы по рискам успешно сохранены.</p>
      </body>
    </html>
    """
    await notifications_api.send_email(email, subject_end, body_end)
    logger.info("Sent ML completion notification email")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate random ML predictions for user.")
    parser.add_argument(
        "--email", "-e",
        dest="email",
        required=True,
        help="Email address of the user whose ML risks will be predicted"
    )
    args = parser.parse_args()

    if not EMAIL_REGEX.fullmatch(args.email):
        logger.error(f"Invalid email format: {args.email}")
        sys.exit(1)

    asyncio.run(main(args.email))
