from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "JotaOrchestrator"
    APP_ENV: str = "development"
    DEBUG: bool = False
    
    REDIS_URL: str
    TRANSCRIPTION_SERVICE_URL: str
    
    INFERENCE_SERVICE_URL: str
    INFERENCE_CLIENT_ID: str
    INFERENCE_API_KEY: str
    
    # JotaDB Integration
    JOTA_DB_URL: str
    JOTA_DB_API_KEY: str
    
    # SSL/TLS & Validation
    SSL_VERIFY: bool = True

    class Config:
        env_file = ".env"

settings = Settings()
