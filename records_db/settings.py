from pydantic_settings import BaseSettings


class DbSettings(BaseSettings):
    RECORDS_DB_ENGINE: str | None = "postgresql+psycopg2"
    # DB_HOST: str = "172.16.57.2"
    RECORDS_DB_HOST: str | None = "25.8.172.192"

    RECORDS_DB_PORT: int | None = 5432
    # DB_USER: str = "services_user"
    # DB_PASSWORD: str = "services_password"
    # DB_NAME: str = "services"

    RECORDS_DB_USER: str | None = "postgres"
    RECORDS_DB_PASSWORD: str | None = "postgres"
    RECORDS_DB_NAME: str | None = "records"

    class Config:
        env_file = ".env"
        # env_file = ".env.development"
        env_file_encoding = "utf-8"
        case_sensitive = False
        env_nested_delimiter = "__"
        extra = "allow"


settings = DbSettings()
