"""
chat/
~~~~~
Endpoint WebSocket para sesiones de chat persistentes.
El REST de /chat ha sido eliminado: usa /api/quick para clientes HTTP.
"""

from fastapi import APIRouter
from .websocket import router as ws_router

router = APIRouter()
router.include_router(ws_router)

__all__ = ["router"]
