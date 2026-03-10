"""
InferenceClient facade and implementation.

This module exports the main `InferenceClient` class, which combines the connection
and session management mixins to provide a high-level API for interacting with the 
InferenceCenter (e.g., listing/loading models and streaming inference tokens).
"""
import asyncio
import time
import json
import logging
from typing import Dict, AsyncGenerator, Any, Optional, List, Union

from src.core.config import settings
from src.core.constants import TOOL_CALL_OPEN, TOOL_CALL_CLOSE, INTERRUPTED_MARKER
from src.core.memory import MemoryManager

from .connection import InferenceConnectionMixin
from .session_manager import InferenceSessionMixin
from .exceptions import InferenceEngineBusyError, ModelNotFoundError

logger = logging.getLogger(__name__)

class InferenceClient(InferenceConnectionMixin, InferenceSessionMixin):
    """
    Cliente WebSocket que mantiene una conexión persistente con el InferenceCenter.

    Internals:
        _response_queues    : Cola asyncio por session_id para streaming de tokens.
        _pending_commands   : Mapa de futures para comandos de gestión (list_models, load_model).
        _pending_sessions   : Futures para creación de sesión en vuelo.
        _auth_future        : Future que se resuelve al completar autenticación.
        _connection_task    : Task del loop de reconexión en background.
    """
    def __init__(self, memory_manager: MemoryManager, url: str = None):
        self.url = url or settings.INFERENCE_SERVICE_URL
        # Usar credenciales del Orchestrator para servicios internos
        self.client_id = settings.ORCHESTRATOR_ID
        self.api_key = settings.ORCHESTRATOR_API_KEY
        self.memory_manager = memory_manager
        
        self.websocket = None
        self.lock = asyncio.Lock()
        
        self.active_sessions: Dict[str, str] = {}
        self._user_sessions: Dict[str, str] = {}  # user_id -> session_id tracking
        self._response_queues: Dict[str, asyncio.Queue] = {}
        self._pending_sessions: Dict[str, asyncio.Future] = {}
        self._pending_commands: Dict[str, asyncio.Future] = {}
        self._session_creation_future: Optional[asyncio.Future] = None
        self._auth_future: Optional[asyncio.Future] = None
        # Modelo actualmente cargado en el InferenceCenter.
        # Nombre sin guión bajo: es estado público observable por el controller.
        self.current_engine_model: Optional[str] = None
        # Lock para serializar cargas de modelo (evita race conditions en el Engine)
        self._model_load_lock: asyncio.Lock = asyncio.Lock()
        # Caché de la lista de modelos disponibles
        self._models_cache: Optional[List] = None
        self._models_cache_expires: float = 0.0   # tiempo monotonic de expiración
        self._models_cache_ttl: float = settings.MODELS_CACHE_TTL

        # Background tasks
        self._connection_task = None
        self._shutdown_event = asyncio.Event()

    async def list_models(self) -> list:
        """Solicita al InferenceCenter la lista de modelos disponibles.

        La respuesta se cachea durante `_models_cache_ttl` segundos (default 5 min).
        Las peticiones dentro de la ventana de TTL devuelven el resultado en memoria
        sin enviar ningún mensaje al bus de comunicación con el Engine.
        """
        now = time.monotonic()
        if self._models_cache is not None and now < self._models_cache_expires:
            logger.debug(f"list_models: returning cached ({int(self._models_cache_expires - now)}s left)")
            return self._models_cache

        if not self.is_connected:
            raise Exception("Inference Engine no conectado")

        future = asyncio.Future()
        self._pending_commands["list_models"] = future

        await self.websocket.send(json.dumps({"op": "COMMAND_LIST_MODELS"}))
        result = await asyncio.wait_for(future, timeout=settings.INFERENCE_LIST_MODELS_TIMEOUT)

        # Actualizar caché
        models = result.get("models", result)  # compatibilidad con distintos formatos
        self._models_cache = models
        self._models_cache_expires = now + self._models_cache_ttl
        logger.info(f"list_models: cache refreshed ({len(models) if isinstance(models, list) else '?'} models, TTL={self._models_cache_ttl}s)")
        return models

    async def load_model(self, model_id: str) -> bool:
        """Solicita la carga de un modelo específico y actualiza el estado local.

        Utiliza _model_load_lock para serializar cargas concurrentes: si dos coroutines
        intentan cargar un modelo al mismo tiempo, la segunda esperará a que termine
        la primera, evitando conflictos de estado en el Engine.

        Raises:
            InferenceEngineBusyError: Si el Engine rechaza por inferencia en progreso.
            ModelNotFoundError: Si el modelo no existe en el Engine.
        """
        if not self.is_connected:
            raise Exception("Inference Engine no conectado")

        async with self._model_load_lock:
            future = asyncio.Future()
            self._pending_commands["load_model"] = future

            logger.info(
                f"[TRACE] Sending COMMAND_LOAD_MODEL to engine — model_id={model_id!r} "
                f"(current_engine_model before={self.current_engine_model!r})"
            )
            await self.websocket.send(json.dumps({
                "op": "COMMAND_LOAD_MODEL",
                "model_id": model_id
            }))

            result = await asyncio.wait_for(future, timeout=settings.INFERENCE_LOAD_MODEL_TIMEOUT)
            logger.info(f"[TRACE] LOAD_MODEL_RESULT from engine — raw={result!r}")
            success = result.get("status") == "SUCCESS"
            if success:
                self.current_engine_model = model_id
                logger.info(
                    f"[TRACE] ✅ Model loaded — current_engine_model={self.current_engine_model!r} — IN SYNC"
                )
            else:
                logger.error(f"[TRACE] ❌ Failed to load model {model_id!r}: {result}")
            return success

    async def infer(
        self,
        session_id: str,
        prompt: str,
        conversation_id: str,
        user_id: str,
        params: Optional[Dict[str, Any]] = None,
        client_id: int = None,
        model_id: Optional[str] = None,
        persist_messages: bool = True,
    ) -> AsyncGenerator[Any, None]:
        """
        Envía un prompt al InferenceCenter y hace streaming de los tokens de respuesta.

        Args:
            model_id: Modelo que generará la respuesta. Se persiste en los metadatos
                      del mensaje resultante para trazabilidad completa.

        Yields:
            str: Fragmentos de texto del modelo conforme llegan (op='token').

        El mensaje completo se persiste en MemoryManager al recibir op='end',
        incluyendo metadata con el model_id para trazabilidad.
        Si la inferencia es interrumpida, guarda la respuesta parcial con '[INTERRUPTED]'.

        Raises:
            Exception: Si el engine no está disponible o se excede el timeout (30s/token).
        """
        if params is None:
            params = {"temp": settings.INFERENCE_DEFAULT_TEMP}

        # Grammar deprecated — model follows JSON format from system prompt.
        # To force grammar: pass params["force_grammar"] = True
        if params.get("force_grammar") and "grammar" not in params:
            from src.core.tool_manager import tool_manager as _tm  # lazy: only when forced
            grammar = _tm.generate_gbnf_grammar()
            if grammar:
                params["grammar"] = grammar
                logger.debug("GBNF grammar injected (forced by client)")

        log_prefix = f"[Conv: {conversation_id}][Sess: {session_id}]"
        response_buffer = []
        yielded_len = 0

        try:
            logger.info(f"{log_prefix} Starting inference...")
            if session_id not in self._response_queues:
                self._response_queues[session_id] = asyncio.Queue()
            
            # Using prompt natively for remote inference as Chat formatting happens downstream
            request = {
                "op": "infer",
                "session_id": session_id,
                "prompt": prompt,
                "params": params
            }
            
            if not self.is_connected:
                 raise Exception("Inference Engine Unavailable")

            await self.websocket.send(json.dumps(request))
            
            queue = self._response_queues[session_id]
            
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=settings.INFERENCE_TOKEN_TIMEOUT)
                except asyncio.TimeoutError:
                    raise Exception("Inference timed out waiting for token")

                if data is None: 
                     raise Exception("Stream interrupted")
                    
                op = data.get("op")
                
                if op == "token":
                    content = data.get("content", "")
                    response_buffer.append(content)
                    full_text = "".join(response_buffer)
                    
                    if TOOL_CALL_OPEN in full_text:
                        start_idx = full_text.find(TOOL_CALL_OPEN)
                        if start_idx > yielded_len:
                            chunk = full_text[yielded_len:start_idx]
                            yielded_len += len(chunk)
                            yield chunk

                        # Check if closed
                        if TOOL_CALL_CLOSE in full_text[start_idx:]:
                            end_idx = full_text.find(TOOL_CALL_CLOSE, start_idx) + len(TOOL_CALL_CLOSE)
                            tool_call_str = full_text[start_idx:end_idx]

                            # Only parse if we haven't yielded this tool call yet
                            if end_idx > yielded_len:
                                yielded_len = end_idx
                                json_str = tool_call_str[len(TOOL_CALL_OPEN):-len(TOOL_CALL_CLOSE)].strip()
                                try:
                                    tool_call_data = json.loads(json_str)
                                    yield {"type": "tool_call", "payload": tool_call_data}
                                except Exception as e:
                                    logger.error(f"Failed to parse tool JSON: {e}")
                                    yield f"\\n[Error parsing tool call: {e}]\\n"
                    else:
                        safe_to_yield = full_text
                        last_lt = full_text.rfind("<")
                        if last_lt != -1 and last_lt >= len(full_text) - len(TOOL_CALL_OPEN):
                            if TOOL_CALL_OPEN.startswith(full_text[last_lt:]):
                                safe_to_yield = full_text[:last_lt]
                                
                        if len(safe_to_yield) > yielded_len:
                            chunk = safe_to_yield[yielded_len:]
                            yielded_len += len(chunk)
                            yield chunk

                elif op == "end":
                    full_text = "".join(response_buffer)
                    if len(full_text) > yielded_len:
                        yield full_text[yielded_len:]
                        
                    if persist_messages:
                        await self.memory_manager.save_message(
                            conversation_id=conversation_id,
                            user_id=user_id,
                            role="assistant",
                            content=full_text,
                            client_id=client_id,
                            metadata={"model_id": model_id} if model_id else None,
                        )
                    logger.info(f"{log_prefix} Inference complete (model={model_id!r}).")
                    break
                elif op == "error":
                    error_msg = data.get("error") or data.get("message") or data.get("content") or str(data)
                    raise Exception(error_msg)
            
        except Exception as e:
            logger.error(f"{log_prefix} Inference error: {e}")
            
            if response_buffer:
                logger.info(f"{log_prefix} Saving interrupted response.")
                partial_response = "".join(response_buffer) + INTERRUPTED_MARKER
                if persist_messages:
                    await self.memory_manager.save_message(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        role="assistant",
                        content=partial_response,
                        client_id=client_id,
                        metadata={"model_id": model_id, "interrupted": True} if model_id else {"interrupted": True},
                    )
            
            await self.memory_manager.mark_conversation_error(conversation_id, user_id)
            raise e
        finally:
             if session_id in self._response_queues:
                 del self._response_queues[session_id]
             logger.debug(f"{log_prefix} Cleaned up queue.")
