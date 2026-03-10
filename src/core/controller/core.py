"""
Core controller for the Orchestrator.

This module exports the main Orchestrator controller (`JotaController`) which unifies
model management and inference input handling by inheriting from mixins.
"""
import logging
from typing import TYPE_CHECKING

from src.core.events import event_bus
from src.services.inference import InferenceClient

from .models import JotaModelMixin
from .input import JotaInputMixin

if TYPE_CHECKING:
    from src.core.memory import MemoryManager

logger = logging.getLogger(__name__)

class JotaController(JotaModelMixin, JotaInputMixin):
    """
    Controlador principal del Orchestrator.

    Args:
        inference_client: Cliente WebSocket con el InferenceCenter.
        memory_manager:   Acceso a JotaDB para leer metadatos de conversaciones.
    """

    def __init__(self, inference_client: InferenceClient, memory_manager: "MemoryManager"):
        self.inference_client = inference_client
        self.memory_manager = memory_manager
        # Suscribir al event_bus para procesamiento desacoplado
        event_bus.subscribe(self.process_event_async)

    async def process_event_async(self, event: dict):
        """
        Wrapper para el event_bus: drena el generator de handle_input.
        """
        async for _ in self.handle_input(event):
            pass
