from fastapi import FastAPI, Response, status
from contextlib import asynccontextmanager
import asyncio
import logging
from src.core.config import settings
from src.api.chat import router as chat_router
# from src.services.transcription import transcription_client  # Disabled until MQTT is available
from src.core.services import inference_client, memory_manager, shutdown_services

logger = logging.getLogger("uvicorn")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up services...")
    
    # Transcription Service - Disabled until MQTT integration is ready
    # task_transcription = asyncio.create_task(transcription_client.connect_and_listen())
    
    # Connect to Inference Service (Lazy connection or explicit)
    try:
        # connect() now starts a background loop with backoff
        await inference_client.connect()
    except Exception as e:
        logger.warning(f"Initial connection to Inference Engine failed (background retry active): {e}")

    yield
    
    # Shutdown
    await shutdown_services()
    
    # await task_transcription  # Disabled until MQTT is available

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan
)

# app.include_router(chat_router, prefix="/api/v1")
app.include_router(chat_router)


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
