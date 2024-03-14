from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    CREDENTIALS_FILE: str
    DATABASE_URL: str


settings = Settings()
