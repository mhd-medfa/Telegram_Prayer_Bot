from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    TELEGRAM_BOT_TOKEN: str
    CREDENTIALS_FILE: str
    DATABASE_URL: str


settings = Settings()
