from typing import Optional

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "JotaOrchestrator"
    APP_ENV: str = "development"
    DEBUG: bool = False
    
    TRANSCRIPTION_SERVICE_URL: str
    
    INFERENCE_SERVICE_URL: str
    
    # Internal Services Authentication
    ORCHESTRATOR_ID: str  # ID del Orchestrator para servicios internos
    ORCHESTRATOR_API_KEY: str  # API Key del Orchestrator para servicios internos
    
    # Tool Config
    TAVILY_API_KEY: Optional[str] = None
    ENABLE_GBNF_GRAMMAR: bool = False  # Deprecated: Use system prompt instead

    
    # JotaDB Integration
    JOTA_DB_URL: str
    JOTA_DB_SK: str  # Server Key - sent as Bearer token for DB access
    
    # SSL/TLS & Validation
    SSL_VERIFY: bool = True

    class Config:
        env_file = ".env"

settings = Settings()
