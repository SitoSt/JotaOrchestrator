from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "JotaOrchestrator"
    APP_ENV: str = "development"
    DEBUG: bool = False
    
    JOTA_DB_URL: str = "http://green-house.local/api/db/"
    JOTA_DB_API_KEY: str = "default_key"  # Should be set via env var
    
    TRANSCRIPTION_SERVICE_URL: str = "ws://localhost:9002"
    INFERENCE_SERVICE_URL: str = "ws://greenhouse.local/api/inference"
    INFERENCE_CLIENT_ID: str = "sito"
    INFERENCE_API_KEY: str = "pene420"

    class Config:
        env_file = ".env"

settings = Settings()
