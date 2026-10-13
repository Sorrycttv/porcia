from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    jwt_secret: str
    jwt_ttl_hours: int = 720
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "your-model-name"
    cors_origins: str = ""


settings = Settings()
