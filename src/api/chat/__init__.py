"""
chat/
~~~~~
Endpoints para la API de Chat (REST y WebSocket).
"""

from fastapi import APIRouter
from .rest import router as rest_router
from .websocket import router as ws_router

router = APIRouter()
router.include_router(rest_router)
router.include_router(ws_router)

__all__ = ["router"]
