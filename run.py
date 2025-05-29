import asyncio
from datetime import datetime
from collections import defaultdict

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from notifications import notifications_api
from db.schemas import RawRecords, OutliersRecords
from settings import Settings
from db.db_session import get_session

settings = Settings()
TARGET_EMAIL = "awesomecosmonaut@gmail.com"

def detect_outliers_zscore(values, threshold=3.0):
    arr = np.array(values, dtype=np.float64)
    mean = arr.mean()
    std = arr.std()
    if std == 0:
        return np.zeros(len(arr), dtype=bool)
    z_scores = np.abs((arr - mean) / std)
    return z_scores > threshold

async def detect_and_store_outliers(session: AsyncSession, iteration_num: int):
    # 1) читаем только записи нужного email
    result = session.execute(
        select(RawRecords)
        .where(RawRecords.email == TARGET_EMAIL)
    )
    records = result.scalars().all()

    # 2) группируем по data_type
    grouped = defaultdict(list)
    for record in records:
        try:
            val = float(record.value)
        except ValueError:
            continue
        grouped[record.data_type].append((record, val))

    now = datetime.utcnow()
    outliers_to_add = []

    # 3) ищем выбросы и готовим объекты
    for data_type, rec_vals in grouped.items():
        recs, vals = zip(*rec_vals)
        mask = detect_outliers_zscore(vals)
        for rec, is_out in zip(recs, mask):
            if is_out:
                outliers_to_add.append(
                    OutliersRecords(
                        raw_record_id=rec.id,
                        outliers_search_iteration_num=iteration_num,
                        outliers_search_iteration_datetime=now,
                    )
                )

    # 4) сохраняем в БД
    session.add_all(outliers_to_add)
    session.commit()
    print(f"Iteration {iteration_num}: added {len(outliers_to_add)} outliers")

async def main():
    # получаем сессию
    session: AsyncSession = await get_session().__anext__()

    # автоматически определяем номер итерации
    result = session.execute(
        select(func.max(OutliersRecords.outliers_search_iteration_num))
    )
    max_iter = result.scalar()
    iteration_number = (max_iter or 0) + 1

    # уведомление о старте
    await notifications_api.send_email(
        TARGET_EMAIL,
        f"Outliers detection iteration #{iteration_number} started",
        "start"
    )

    # основной анализ и сохранение
    await detect_and_store_outliers(session, iteration_number)

    # уведомление о завершении
    await notifications_api.send_email(
        TARGET_EMAIL,
        f"Outliers detection iteration #{iteration_number} completed",
        "end"
    )

if __name__ == "__main__":
    asyncio.run(main())
