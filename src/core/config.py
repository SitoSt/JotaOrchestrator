from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "JotaOrchestrator"
    APP_ENV: str = "development"
    DEBUG: bool = False
    
    REDIS_URL: str = "redis://localhost:6379/0"
    TRANSCRIPTION_SERVICE_URL: str = "ws://localhost:9002"
    INFERENCE_SERVICE_URL: str = "ws://localhost:9001"

    class Config:
        env_file = ".env"

settings = Settings()
