from fastapi import FastAPI
from contextlib import asynccontextmanager
import asyncio
from src.core.config import settings
from src.api.chat import router as chat_router
from src.services.transcription import transcription_client
from src.services.inference import inference_client
# Controller initialized on import
from src.core.controller import jota_controller 

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger = logging.getLogger("uvicorn")
    logger.info("Starting up services...")
    
    # Transcription Service
    task_transcription = asyncio.create_task(transcription_client.connect_and_listen())
    
    # Inference Service connection is lazy (on first request) or explicit?
    # "connect()" checks if connected. We can pre-connect here.
    try:
        await inference_client.connect()
    except Exception as e:
        logger.warning(f"Initial connection to Inference Engine failed: {e}")

    yield
    
    # Shutdown
    logger.info("Shutting down services...")
    transcription_client.stop()
    await inference_client.invoke_shutdown()
    
    await task_transcription
    if inference_client.websocket:
        await inference_client.websocket.close()

import logging

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan
)

app.include_router(chat_router, prefix="/api/v1")

@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "environment": settings.APP_ENV,
        "status": "online"
    }

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
