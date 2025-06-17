from records_db.engine import records_db_engine


async def get_records_db_session():
    session = records_db_engine.create_session()
    try:
        yield session
    finally:
        session.close()
