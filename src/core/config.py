from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "JotaOrchestrator"
    APP_ENV: str = "development"
    DEBUG: bool = False

    TRANSCRIPTION_SERVICE_URL: str

    INFERENCE_SERVICE_URL: str

    # Internal Services Authentication
    ORCHESTRATOR_ID: str       # ID del Orchestrator para servicios internos
    ORCHESTRATOR_API_KEY: str  # API Key del Orchestrator para servicios internos

    # ---------------------------------------------------------------------------
    # Agent personality
    # ---------------------------------------------------------------------------
    AGENT_BASE_SYSTEM_PROMPT: str = (
        "You are Jota, a helpful and friendly AI assistant. "
        "Respond concisely and naturally. Keep answers short — "
        "use a few sentences unless the user explicitly asks for detail. "
        "Match the language the user writes in."
    )
    TOOL_FOLLOWUP_PROMPT: str = (
        "The tool has provided the results. "
        "Please answer the original user query using this information."
    )

    # ---------------------------------------------------------------------------
    # Inference parameters
    # ---------------------------------------------------------------------------
    INFERENCE_DEFAULT_TEMP: float = 0.7
    INFERENCE_TOKEN_TIMEOUT: float = 30.0     # seconds to wait for next token
    INFERENCE_LOAD_MODEL_TIMEOUT: float = 30.0
    INFERENCE_LIST_MODELS_TIMEOUT: float = 10.0
    INFERENCE_SESSION_TIMEOUT: float = 5.0
    MODELS_CACHE_TTL: float = 300.0           # seconds model list is cached

    # ---------------------------------------------------------------------------
    # Tool output limits
    # ---------------------------------------------------------------------------
    TOOL_MAX_OUTPUT_CHARS: int = 4000         # cap before truncation in tool_manager
    MEMORY_TOOL_OUTPUT_CAP: int = 1500        # cap when injecting tool results into context

    # ---------------------------------------------------------------------------
    # Tool Config
    # ---------------------------------------------------------------------------
    TAVILY_API_KEY: Optional[str] = None
    TAVILY_SEARCH_DEPTH: str = "basic"
    TAVILY_MAX_RESULTS: int = 5
    ENABLE_GBNF_GRAMMAR: bool = False         # Deprecated: Use system prompt instead

    # ---------------------------------------------------------------------------
    # MQTT Integration
    # ---------------------------------------------------------------------------
    MQTT_ENABLED: bool = False
    MQTT_BROKER_HOST: str = "localhost"
    MQTT_BROKER_PORT: int = 1883
    MQTT_USERNAME: Optional[str] = None
    MQTT_PASSWORD: Optional[str] = None
    MQTT_CLIENT_ID: str = "jota-orchestrator"
    MQTT_KEEPALIVE: int = 60
    MQTT_QOS: int = 1
    MQTT_SUBSCRIBE_TOPIC: str = "jota/transcriptions"
    MQTT_RESPONSE_TOPIC_PREFIX: str = "jota/responses"
    MQTT_CLIENT_SYSTEM_PROMPT: str = (
        "You are Jota, a voice command assistant. "
        "Respond ONLY with 1-2 short phrases. "
        "No explanations, no pleasantries — just the direct result or answer. "
        "Match the language the user writes in."
    )

    # ---------------------------------------------------------------------------
    # JotaDB Integration
    # ---------------------------------------------------------------------------
    JOTA_DB_URL: str
    JOTA_DB_SK: str            # Server Key - sent as Bearer token for DB access
    JOTA_DB_TIMEOUT: float = 10.0

    # ---------------------------------------------------------------------------
    # CORS
    # ---------------------------------------------------------------------------
    CORS_ORIGINS: list[str] = ["*"]

    # SSL/TLS & Validation
    SSL_VERIFY: bool = True

    class Config:
        env_file = ".env"


settings = Settings()
