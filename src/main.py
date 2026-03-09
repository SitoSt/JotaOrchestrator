from fastapi import FastAPI, Response, status
from contextlib import asynccontextmanager
import asyncio
import logging
from src.core.config import settings
from src.api.chat import router as chat_router
from src.api.quick import router as quick_router
# from src.services.transcription import transcription_client  # Disabled until MQTT is available
from src.core.services import inference_client, memory_manager, mqtt_service, shutdown_services

# Configure root logger so all src.* loggers propagate to the console.
# Gunicorn only sets up gunicorn.*/uvicorn.* loggers; without this,
# all application-level logs are silently dropped.
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(name)s - %(message)s",
)

logger = logging.getLogger("uvicorn")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("=" * 60)
    logger.info("🚀 INICIANDO JOTA ORCHESTRATOR")
    logger.info("=" * 60)
    
    # Transcription Service - Disabled until MQTT integration is ready
    # task_transcription = asyncio.create_task(transcription_client.connect_and_listen())
    
    # 1. Verify JotaDB Connection with Authentication
    logger.info("📊 Verificando conexión con JotaDB...")
    logger.info(f"   └─ URL: {settings.JOTA_DB_URL}")
    try:
        db_connected = await memory_manager.verify_connection()
        if db_connected:
            logger.info("✅ JotaDB: CONECTADO y AUTENTICADO correctamente")
        else:
            logger.error("❌ JotaDB: FALLO en la conexión o autenticación")
            logger.error("   └─ El servicio continuará pero la funcionalidad estará limitada")
    except Exception as e:
        logger.error(f"❌ JotaDB: ERROR al verificar conexión - {e}")
    
    logger.info("")  # Línea en blanco para separar
    
    # 2. Connect to Inference Service with Authentication
    logger.info("🧠 Conectando con Inference Engine...")
    logger.info(f"   └─ URL: {settings.INFERENCE_SERVICE_URL}")
    logger.info(f"   └─ Orchestrator ID: {settings.ORCHESTRATOR_ID}")
    try:
        # Iniciar el loop de conexión
        await inference_client.connect()
        
        # Esperar a que se autentique (con timeout)
        inference_connected = await inference_client.verify_connection()
        
        if inference_connected:
            logger.info("✅ Inference Engine: CONECTADO y AUTENTICADO correctamente")
        else:
            logger.warning("⚠️  Inference Engine: Conexión en progreso (reintentando en segundo plano)")
    except Exception as e:
        logger.warning(f"⚠️  Inference Engine: Conexión inicial fallida (reintentando en segundo plano) - {e}")
    
    logger.info("")  # Línea en blanco

    # 3. Connect to MQTT broker (if enabled)
    if settings.MQTT_ENABLED:
        logger.info("📡 Conectando con broker MQTT...")
        logger.info(f"   └─ Broker: {settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}")
        logger.info(f"   └─ Topic:  {settings.MQTT_SUBSCRIBE_TOPIC}")
        await mqtt_service.connect()
        logger.info("✅ MQTT: Suscrito y escuchando")
        logger.info("")  # Línea en blanco

    logger.info("=" * 60)
    logger.info("✨ JotaOrchestrator listo para recibir peticiones")
    logger.info("=" * 60)

    yield
    
    # Shutdown
    logger.info("🛑 Cerrando servicios...")
    await shutdown_services()
    logger.info("👋 JotaOrchestrator detenido")
    
    # await task_transcription  # Disabled until MQTT is available

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan
)

_cors_origins = settings.CORS_ORIGINS
_allow_credentials = "*" not in _cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# app.include_router(chat_router, prefix="/api/v1")
app.include_router(chat_router)
app.include_router(quick_router)


@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "environment": settings.APP_ENV,
        "status": "online"
    }

@app.get("/health")
async def health_check(response: Response):
    """
    Deep Health Check.
    Verifies connectivity to JotaDB and Inference Engine.
    """
    inference_status = await inference_client.check_health()
    memory_status = await memory_manager.check_health()
    
    status_code = status.HTTP_200_OK
    if not inference_status or not memory_status:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        response.status_code = status_code

    return {
        "status": "ok" if status_code == 200 else "degraded",
        "components": {
            "inference_engine": "connected" if inference_status else "disconnected",
            "jota_db": "connected" if memory_status else "disconnected"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
