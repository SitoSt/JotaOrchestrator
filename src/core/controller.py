"""
controller.py
~~~~~~~~~~~~~
Orquesta el flujo de entrada de usuario hacia el InferenceCenter.

Responsabilidades:
  - Verificar que el modelo configurado para la conversación esté cargado
    en el InferenceCenter antes de cada inferencia.
  - Delegar el streaming de tokens al InferenceClient.
  - Actuar como suscriptor del event_bus para procesamiento desacoplado.
"""
import logging
from typing import AsyncGenerator, TYPE_CHECKING

from src.core.events import event_bus
from src.services.inference import InferenceClient

if TYPE_CHECKING:
    from src.core.memory import MemoryManager

logger = logging.getLogger(__name__)


class JotaController:
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

    async def _ensure_model_loaded(self, conversation_id: str, client_id) -> None:
        """
        Verifica que el modelo vinculado a la conversación esté activo en el motor.
        Si difiere del modelo actualmente cargado, ordena la carga del correcto.
        Si la conversación no tiene model_id, no fuerza ningún cambio.
        """
        conversation = await self.memory_manager.get_conversation(conversation_id, client_id)
        if not conversation:
            logger.warning(f"Could not fetch conversation {conversation_id} to check model.")
            return

        required_model = conversation.get("model_id")
        if not required_model:
            logger.debug(f"Conversation {conversation_id} has no model_id set. Skipping model check.")
            return

        active_model = self.inference_client._active_model_id
        if active_model == required_model:
            logger.debug(f"Model '{required_model}' already active. No switch needed.")
            return

        logger.info(f"⚙️  Model mismatch: active='{active_model}' required='{required_model}'. Loading...")
        success = await self.inference_client.load_model(required_model)
        if not success:
            raise RuntimeError(f"Failed to load required model '{required_model}' for conversation {conversation_id}")

    async def handle_input(self, payload: dict) -> AsyncGenerator[str, None]:
        """
        Flujo principal por petición:
          1. Verificar y cargar el modelo de la conversación si es necesario.
          2. Hacer streaming de tokens desde el InferenceCenter.

        Los mensajes de usuario/asistente son persistidos por chat.py e InferenceClient
        respectivamente; el controller no los gestiona directamente.
        """
        content = payload.get("content")
        session_id = payload.get("session_id")
        conversation_id = payload.get("conversation_id")
        user_id = payload.get("user_id")
        client_id = payload.get("client_id")

        if not session_id or not conversation_id or not user_id:
            logger.error("Missing session_id, conversation_id, or user_id in payload")
            yield " [Error: Internal Context Missing]"
            return

        logger.info(f"Controller processing input for session {session_id}")

        try:
            # Pre-infer: garantizar que el modelo correcto está cargado
            await self._ensure_model_loaded(conversation_id, client_id)

            logger.info("Streaming from Inference Engine...")
            async for token in self.inference_client.infer(
                session_id=session_id,
                prompt=content,
                conversation_id=conversation_id,
                user_id=user_id,
                params=None,
                client_id=client_id,
            ):
                yield token

            logger.info("Inference stream complete.")

        except Exception as e:
            logger.error(f"Error during inference flow: {e}")
            yield f" [Error: {str(e)}]"
