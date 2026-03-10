"""
Model management logic for the Orchestrator Controller.

Provides `JotaModelMixin`, responsible for robust model switching, tracking active 
models on the InferenceCenter, and ensuring database consistency.
"""
import asyncio
import logging
from typing import TYPE_CHECKING

from src.services.inference import InferenceEngineBusyError, ModelNotFoundError

if TYPE_CHECKING:
    from src.core.memory import MemoryManager
    from src.services.inference import InferenceClient

logger = logging.getLogger(__name__)

_LOAD_MAX_RETRIES = 3
_LOAD_BASE_DELAY = 1.0  # segundos

class JotaModelMixin:
    """
    Mixin para manejar la carga de modelos en el InferenceCenter.
    """

    async def switch_model(self, conversation_id: str, client_id, model_id: str) -> None:
        """
        Cambia el modelo activo de forma atómica: primero lo carga en el Engine
        y solo si el Engine confirma SUCCESS actualiza la DB.

        Es la única fuente de verdad para cambios de modelo. Se usa en:
          - Reconexión WS con nuevo model_id (chat.py)
          - Comandos de cambio de modelo en mitad de sesión (chat.py WS loop)
          - _ensure_model_loaded cuando detecta un mismatch engine ↔ DB

        Args:
            conversation_id: ID de la conversación a actualizar.
            client_id:       ID del cliente propietario de la conversación.
            model_id:        Modelo destino a cargar.

        Raises:
            ModelNotFoundError:      Si el modelo no existe en el catálogo del Engine.
            InferenceEngineBusyError: Si el Engine sigue ocupado tras todos los reintentos.
            RuntimeError:            Si la carga falla por razón desconocida.
        """
        logger.info(
            f"[TRACE][Conv: {conversation_id}] switch_model called — "
            f"target={model_id!r} engine_current={self.inference_client.current_engine_model!r}"
        )

        if self.inference_client.current_engine_model == model_id:
            # El engine ya tiene el modelo — solo aseguramos que la DB esté en sync.
            await self.memory_manager.set_conversation_model(conversation_id, client_id, model_id)
            logger.info(
                f"[TRACE][Conv: {conversation_id}] ✅ Model already active: {model_id!r}. "
                f"DB synced, no engine switch needed."
            )
            return

        # — Validación de existencia pre-carga (falla rápida) —
        try:
            available = await self.inference_client.list_models()
            if isinstance(available, list) and available:
                ids = [m.get("id") or m.get("model_id") or m for m in available]
                if model_id not in ids:
                    logger.error(f"[TRACE][Conv: {conversation_id}] Model {model_id!r} not in Engine catalog: {ids}")
                    raise ModelNotFoundError(f"Model '{model_id}' not found in Engine catalog")
                logger.info(
                    f"[TRACE][Conv: {conversation_id}] Model {model_id!r} confirmed in Engine catalog ({len(ids)} models)."
                )
        except ModelNotFoundError:
            raise
        except Exception as e:
            logger.warning(f"[TRACE][Conv: {conversation_id}] Could not validate catalog (proceeding anyway): {e}")

        # — Carga con backoff exponencial —
        logger.info(
            f"[TRACE][Conv: {conversation_id}] ⚠️ Sending COMMAND_LOAD_MODEL — "
            f"active={self.inference_client.current_engine_model!r} → target={model_id!r}"
        )

        delay = _LOAD_BASE_DELAY
        success = False
        for attempt in range(1, _LOAD_MAX_RETRIES + 1):
            try:
                success = await self.inference_client.load_model(model_id)
                break
            except InferenceEngineBusyError:
                if attempt == _LOAD_MAX_RETRIES:
                    logger.error(f"[TRACE][Conv: {conversation_id}] Engine busy after {_LOAD_MAX_RETRIES} retries. Giving up.")
                    raise
                logger.warning(
                    f"[TRACE][Conv: {conversation_id}] Engine busy (attempt {attempt}/{_LOAD_MAX_RETRIES}). "
                    f"Retrying in {delay:.0f}s..."
                )
                await asyncio.sleep(delay)
                delay *= 2

        if success:
            # Atomicidad: DB solo se actualiza tras confirmación del Engine.
            await self.memory_manager.set_conversation_model(conversation_id, client_id, model_id)
            logger.info(
                f"[TRACE][Conv: {conversation_id}] ✅ switch_model OK — "
                f"engine_model={self.inference_client.current_engine_model!r} "
                f"db_model={model_id!r} — IN SYNC"
            )
        else:
            raise RuntimeError(
                f"Failed to load model '{model_id}' for conversation {conversation_id}"
            )

    async def _ensure_model_loaded(self, conversation_id: str, client_id) -> None:
        """
        Verifica antes de cada inferencia que el modelo de la DB esté cargado en el Engine.
        Delega a switch_model si detecta un mismatch.

        Raises:
            ModelNotFoundError:      propagado desde switch_model.
            InferenceEngineBusyError: propagado desde switch_model.
            RuntimeError:            propagado desde switch_model.
        """
        conversation = await self.memory_manager.get_conversation(conversation_id, client_id)
        if not conversation:
            logger.warning(f"Could not fetch conversation {conversation_id} to check model.")
            return

        required_model = conversation.get("model_id")
        if not required_model:
            logger.debug(f"Conversation {conversation_id} has no model_id set. Skipping model check.")
            return

        logger.info(
            f"[TRACE][Conv: {conversation_id}] _ensure_model_loaded — "
            f"db_model={required_model!r} engine_current={self.inference_client.current_engine_model!r}"
        )

        if self.inference_client.current_engine_model == required_model:
            logger.info(
                f"[TRACE][Conv: {conversation_id}] ✅ Model already active: {required_model!r}. No switch needed."
            )
            return

        # Mismatch detectado — switch_model es la única fuente de verdad para cambios de modelo.
        await self.switch_model(conversation_id, client_id, required_model)
