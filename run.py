import asyncio
import argparse
import logging
import re
import sys
from datetime import datetime
from collections import defaultdict

import numpy as np
from sqlalchemy.future import select
from sqlalchemy import func

from notifications import notifications_api
from db.schemas import RawRecords, OutliersRecords
from settings import Settings
from db.db_session import get_session

# Настройки
settings = Settings()
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# Конфигурация логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

def detect_outliers_zscore(values, threshold=3.0):
    arr = np.array(values, dtype=np.float64)
    mean = arr.mean()
    std = arr.std()
    if std == 0:
        return np.zeros(len(arr), dtype=bool)
    z_scores = np.abs((arr - mean) / std)
    return z_scores > threshold

async def detect_and_store_outliers(session, target_email: str, iteration_num: int):
    logger.info(f"Iteration {iteration_num}: starting outlier detection for {target_email}")

    # 1) читаем записи
    result = session.execute(
        select(RawRecords).where(RawRecords.email == target_email)
    )
    records = result.scalars().all()
    total_records = len(records)
    logger.info(f"Fetched {total_records} raw records for {target_email}")

    # 2) группируем по data_type
    grouped = defaultdict(list)
    for record in records:
        try:
            val = float(record.value)
        except ValueError:
            logger.warning(f"Skipping non-numeric value in record id={record.id}")
            continue
        grouped[record.data_type].append((record, val))
    logger.info(f"Grouped records into {len(grouped)} data types")

    now = datetime.utcnow()
    outliers_to_add = []
    per_type_counts = {}

    # 3) ищем выбросы
    for data_type, rec_vals in grouped.items():
        recs, vals = zip(*rec_vals)
        mask = detect_outliers_zscore(vals)
        cnt = int(mask.sum())
        per_type_counts[data_type] = cnt
        logger.info(f"DataType '{data_type}': found {cnt} outliers out of {len(vals)} records")
        for rec, is_out in zip(recs, mask):
            if is_out:
                outliers_to_add.append(
                    OutliersRecords(
                        raw_record_id=rec.id,
                        outliers_search_iteration_num=iteration_num,
                        outliers_search_iteration_datetime=now,
                    )
                )

    # 4) сохраняем
    session.add_all(outliers_to_add)
    session.commit()
    logger.info(f"Iteration {iteration_num}: committed {len(outliers_to_add)} outliers to DB")

    return {
        "total_records": total_records,
        "total_outliers": len(outliers_to_add),
        "per_type": per_type_counts,
        "started_at": now
    }

async def main(target_email: str):
    logger.info(f"Script started for email: {target_email}")
    session = await get_session().__anext__()

    # определяем итерацию
    result = session.execute(
        select(func.max(OutliersRecords.outliers_search_iteration_num))
        .join(RawRecords, OutliersRecords.raw_record_id == RawRecords.id)
        .where(RawRecords.email == target_email)
    )
    max_iter = result.scalar()
    iteration_number = (max_iter or 0) + 1
    logger.info(f"Next outlier iteration number: {iteration_number}")

    start_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    subject_start = f"[Iteration #{iteration_number}] Запуск поиска выбросов"
    body_start = f"""
    <html>
      <body>
        <h2>🔍 Итерация #{iteration_number} — Запуск</h2>
        <p><strong>Пользователь:</strong> {target_email}</p>
        <p><strong>Время запуска:</strong> {start_time}</p>
        <p>Начинаем сканирование всех записей для поиска выбросов.</p>
      </body>
    </html>
    """
    await notifications_api.send_email(target_email, subject_start, body_start)
    logger.info("Sent start notification email")

    summary = await detect_and_store_outliers(session, target_email, iteration_number)

    finish_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    subject_end = f"[Iteration #{iteration_number}] Завершение поиска выбросов"
    rows = "".join(
        f"<tr><td>{dt}</td><td style='text-align:center'>{cnt}</td></tr>"
        for dt, cnt in summary["per_type"].items()
    )
    body_end = f"""
    <html>
      <body>
        <h2>✅ Итерация #{iteration_number} завершена</h2>
        <p><strong>Пользователь:</strong> {target_email}</p>
        <p><strong>Время старта:</strong> {start_time}</p>
        <p><strong>Время окончания:</strong> {finish_time}</p>
        <p><strong>Всего записей проверено:</strong> {summary["total_records"]}</p>
        <p><strong>Найдено выбросов:</strong> {summary["total_outliers"]}</p>
        <h3>Расчёт по типам данных</h3>
        <table border="1" cellpadding="5" cellspacing="0">
          <thead>
            <tr><th>Тип данных</th><th>Выбросов</th></tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
      </body>
    </html>
    """
    await notifications_api.send_email(target_email, subject_end, body_end)
    logger.info("Sent completion notification email and script finished")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run outliers detection for a given user email."
    )
    parser.add_argument(
        "--email", "-e",
        dest="email",
        required=True,
        help="Email address of the user whose records will be processed"
    )
    args = parser.parse_args()

    if not EMAIL_REGEX.fullmatch(args.email):
        logger.error(f"Invalid email format: {args.email}")
        sys.exit(1)

    asyncio.run(main(args.email))
