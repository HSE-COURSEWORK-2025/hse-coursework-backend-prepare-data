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
from records_db.schemas import MLPredictionsRecords, RawRecords, ProcessedRecords
from records_db.db_session import get_records_db_session

from settings import Settings
from sqlalchemy.orm import Session
from sqlalchemy import insert, select, func, cast, Numeric

# Настройки
settings = Settings()
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def process_data(records_db_session: Session, email: str):

    data_types = [
        "ActiveCaloriesBurnedRecord",
        "ActiveMinutesRecord",
        "DistanceRecord",
        "HeartMinutesRecord",
        "SleepSessionTimeData",
        "StepsRecord",
        "TotalCaloriesBurnedRecord",
    ]

    for data_type in data_types:
        query = (
            select(
                func.date(RawRecords.time).label("record_date"),
                func.sum(
                    func.cast(
                        func.regexp_replace(RawRecords.value, "[^0-9\.]+", "", "g"),
                        Numeric,
                    )
                ).label("value_sum"),
            )
            .where(RawRecords.data_type == data_type, RawRecords.email == email)
            .group_by(func.date(RawRecords.time))
            .order_by(func.date(RawRecords.time))
        )
        result = records_db_session.execute(
            query, {"data_type": data_type, "email": email}
        )

        rows = result.fetchall()
        for record_date, value_sum in rows:

            exists_stmt = select(ProcessedRecords.id).where(
                ProcessedRecords.email == email,
                ProcessedRecords.data_type == data_type,
                ProcessedRecords.time == record_date,
            )
            existing_id = (records_db_session.execute(exists_stmt)).scalars().first()
            if existing_id:
                # пропускаем, если уже есть
                continue
            stmt = insert(ProcessedRecords).values(
                email=email,
                data_type=data_type,
                time=record_date,  # в вашей модели поле называется `time`
                value=str(value_sum),  # если в модели `value` — Text, сохраняем строку
            )
            records_db_session.execute(stmt)
        try:
            records_db_session.commit()
        except Exception as e:
            records_db_session.rollback()

    speed_query = (
        select(
            func.date(RawRecords.time).label("record_date"),
            func.avg(
                cast(
                    func.regexp_replace(RawRecords.value, "[^0-9\.]+", "", "g"), Numeric
                )
            ).label("avg_speed"),
        )
        .where(RawRecords.data_type == "SpeedRecord", RawRecords.email == email)
        .group_by(func.date(RawRecords.time))
        .order_by(func.date(RawRecords.time))
    )
    speed_result = records_db_session.execute(speed_query)
    speed_rows = speed_result.fetchall()

    for record_date, avg_speed in speed_rows:
        # Проверяем, не записаны ли мы уже
        exists_stmt = select(ProcessedRecords.id).where(
            ProcessedRecords.email == email,
            ProcessedRecords.data_type == "SpeedRecord",
            ProcessedRecords.time == record_date,
        )
        if records_db_session.execute(exists_stmt).scalars().first():
            continue

        # Вставляем среднюю скорость как новую запись
        stmt = insert(ProcessedRecords).values(
            email=email,
            data_type="SpeedRecord",
            time=record_date,
            value=str(avg_speed),
        )
        records_db_session.execute(stmt)

    # Коммитим ВСЕ изменения разом
    try:
        records_db_session.commit()
    except Exception:
        records_db_session.rollback()
        raise


async def send_preprocessing_start_notification(
    email: str, start_time: str
):
    subject = f"[Data Prep Iteration] Начало предобработки данных"
    body = f"""
    <html>
      <body>
        <h2>🔄 Предобработка данных — Начало итерации</h2>
        <p><strong>Пользователь:</strong> {email}</p>
        <p><strong>Время начала:</strong> {start_time}</p>
        <p>Запускается этап предобработки данных.</p>
      </body>
    </html>
    """
    await notifications_api.send_email(email, subject, body)
    logger.info("Sent data preprocessing start notification email")


async def send_preprocessing_completion_notification(
    email: str, start_time: str, finish_time: str
):
    subject = f"[Data Prep Iteration ] Завершение предобработки данных"
    body = f"""
    <html>
      <body>
        <h2>✅ Предобработка данных — Итерация завершена</h2>
        <p><strong>Пользователь:</strong> {email}</p>
        <p><strong>Время начала:</strong> {start_time}</p>
        <p><strong>Время окончания:</strong> {finish_time}</p>
        <p>Все данные успешно предобработаны и сохранены.</p>
      </body>
    </html>
    """
    await notifications_api.send_email(email, subject, body)
    logger.info("Sent data preprocessing completion notification email")


async def main(email: str):
    # Определяем итерацию
    records_db_session = await get_records_db_session().__anext__()


    start_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    try:
        await send_preprocessing_start_notification(email, start_time)
    except Exception as e:
        logger.error(f"Failed to send ML start notification: {e}")

    # Генерируем и сохраняем прогнозы
    await process_data(records_db_session, email)

    finish_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    try:
        await send_preprocessing_completion_notification(
            email, start_time, finish_time
        )
    except Exception as e:
        logger.error(f"Failed to send ML completion notification: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Preprocess data for user."
    )
    parser.add_argument(
        "--email",
        "-e",
        dest="email",
        required=True,
        help="Email address of the user",
    )
    args = parser.parse_args()

    if not EMAIL_REGEX.fullmatch(args.email):
        logger.error(f"Invalid email format: {args.email}")
        sys.exit(1)

    asyncio.run(main(args.email))
