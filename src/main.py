from fastapi import FastAPI
from contextlib import asynccontextmanager
import asyncio
from src.core.config import settings
from src.api.chat import router as chat_router
from src.services.transcription import transcription_client
from src.core.controller import jota_controller # Initializes subscription

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    task = asyncio.create_task(transcription_client.connect_and_listen())
    yield
    # Shutdown
    transcription_client.stop()
    await task

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
