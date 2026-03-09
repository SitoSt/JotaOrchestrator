"""
inference.py
~~~~~~~~~~~~
Cliente WebSocket persistente para comunicarse con el InferenceCenter.

Responsabilidades:
  - Mantener una conexión WebSocket con reconexión automática (backoff exponencial).
  - Gestionar el ciclo de vida de las sesiones de inferencia por usuario.
  - Despachar mensajes del protocolo a handlers tipados (dispatch table).
  - Ejecutar comandos de gestión de modelos (list_models, load_model) de forma async.

Protocolo (operaciones entrantes):
  hello             → Confirmación de conexión inicial.
  auth_success      → Autenticación aceptada por el servidor.
  error             → Error de protocolo o autenticación.
  session_created   → Respuesta a 'create_session'.
  session_error     → Fallo al crear sesión.
  LIST_MODELS_RESULT→ Respuesta a COMMAND_LIST_MODELS.
  LOAD_MODEL_RESULT → Respuesta a COMMAND_LOAD_MODEL.
  token / end       → Tokens de streaming de inferencia.
"""
import asyncio
import time
import websockets
import json
import logging
import ssl
from typing import Dict, AsyncGenerator, Any, Optional, List, Union

from src.core.config import settings
from src.core.constants import TOOL_CALL_OPEN, TOOL_CALL_CLOSE, INTERRUPTED_MARKER
from src.core.memory import MemoryManager



logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class InferenceEngineBusyError(Exception):
    """El Engine rechazó el comando porque hay una inferencia en progreso."""


class ModelNotFoundError(Exception):
    """El Engine no encontró el modelo solicitado."""


class InferenceClient:
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

    @property
    def is_connected(self) -> bool:
        """Robustly checks if the websocket is connected."""
        if not self.websocket:
            return False
        if hasattr(self.websocket, 'open'):
            return self.websocket.open
        if hasattr(self.websocket, 'state'):
            return getattr(self.websocket.state, 'name', '') == 'OPEN'
        return not getattr(self.websocket, 'closed', False)

    async def connect(self):
        """
        Starts the persistent connection loop in the background.
        """
        if self._connection_task and not self._connection_task.done():
            return
        
        self._shutdown_event.clear()
        self._connection_task = asyncio.create_task(self._connection_loop())
        logger.info("Inference Client connection loop started.")

    async def invoke_shutdown(self):
        """
        Signals shutdown and cleans up resources.
        """
        self._shutdown_event.set()
        if self._connection_task:
            self._connection_task.cancel()
            try:
                await self._connection_task
            except asyncio.CancelledError:
                pass
        
        if self.websocket:
            await self.websocket.close()

    async def check_health(self) -> bool:
        """
        Checks if the WebSocket connection is active and authenticated.
        """
        return self.is_connected

    async def verify_connection(self, timeout: float = 10.0) -> bool:
        """
        Verifica que la conexión con Inference Engine esté establecida Y autenticada.
        Espera hasta que la autenticación se complete o hasta timeout.
        """
        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            if self.is_connected:
                # Verificar si ya pasó la autenticación
                if self._auth_future and self._auth_future.done():
                     # Si terminó y no lanzó excepción, es True (o el resultado)
                     try:
                         if self._auth_future.result():
                             logger.debug("✅ Inference Engine autenticado correctamente")
                             return True
                     except Exception:
                         pass # Falló la auth
            
            # Esperar un poco antes de verificar de nuevo
            await asyncio.sleep(0.1)
        
        logger.error("❌ Timeout esperando autenticación con Inference Engine")
        return False

    async def _connection_loop(self):
        """
        Maintains connection to the Inference Engine with exponential backoff.
        Supports SSL/TLS and Auth Handshake.
        """
        backoff_delay = 1
        max_backoff = 60

        while not self._shutdown_event.is_set():
            try:
                logger.info(f"🔌 Intentando conectar con Inference Engine: {self.url}")
                
                # Configure SSL Context if needed (HEAD logic)
                ssl_context = None
                if self.url.startswith("wss://"):
                    ssl_context = ssl.create_default_context()
                    if not settings.SSL_VERIFY:
                        logger.warning("⚠️  SSL Verification deshabilitada para InferenceClient")
                        ssl_context.check_hostname = False
                        ssl_context.verify_mode = ssl.CERT_NONE
                
                # Headers para autenticación
                additional_headers = {
                    "X-Client-ID": self.client_id,
                    "X-API-Key": self.api_key
                }
                
                logger.info(f"Connecting to {self.url} with Client ID: {self.client_id}")
                
                async with websockets.connect(self.url, ssl=ssl_context, additional_headers=additional_headers) as websocket:
                    self.websocket = websocket
                    backoff_delay = 1 # Reset backoff on successful connection
                    logger.info("✅ WebSocket conectado y autenticado por headers")
                    
                    # Marcar como autenticado inmediatamente ya que la conexión fue aceptada
                    # Si la autenticación falla, el servidor cerrará la conexión (Handshake failure)
                    self._auth_future = asyncio.Future()
                    self._auth_future.set_result(True)
                    
                    # Start read loop
                    read_task = asyncio.create_task(self._read_loop())
                    
                    # Run read loop while connected (await the task)
                    try:
                        await read_task
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.error(f"Read loop error: {e}")
            
            except (websockets.exceptions.ConnectionClosed, OSError, asyncio.TimeoutError) as e:
                logger.error(f"Connection failed/dropped: {e}. Retrying in {backoff_delay}s...")
                self.websocket = None
                
            except Exception as e:
                logger.error(f"Unexpected error in connection loop: {e}. Retrying in {backoff_delay}s...")
                self.websocket = None

            if self._shutdown_event.is_set():
                break

            # Backoff wait
            await asyncio.sleep(backoff_delay)
            backoff_delay = min(backoff_delay * 2, max_backoff)

    # ---------------------------------------------------------------------------
    # Protocol message handlers (dispatch table)
    # ---------------------------------------------------------------------------

    async def _handle_hello(self, data: dict, session_id: str | None) -> None:
        logger.info(f"Received hello: {data.get('message', 'ready')}")

    async def _handle_auth_success(self, data: dict, session_id: str | None) -> None:
        logger.info(f"Auth Success: {data}")
        if self._auth_future and not self._auth_future.done():
            self._auth_future.set_result(True)

    async def _handle_error(self, data: dict, session_id: str | None) -> None:
        error_msg = data.get("error") or data.get("message") or "Unknown error"
        logger.error(f"Server Error: {error_msg}")

        # Mapear mensajes de error del Engine a excepciones tipadas
        if error_msg == "ERROR_INFERENCE_IN_PROGRESS":
            exc: Exception = InferenceEngineBusyError(error_msg)
        elif error_msg == "ERROR_MODEL_NOT_FOUND":
            exc = ModelNotFoundError(error_msg)
        else:
            exc = Exception(error_msg)

        # Prioridad 1: error durante autenticación
        if self._auth_future and not self._auth_future.done():
            self._auth_future.set_exception(exc)
            return

        # Prioridad 2: error en respuesta a un comando pendiente (load/list models)
        for future in self._pending_commands.values():
            if not future.done():
                future.set_exception(exc)
                return

        # Prioridad 3: error dentro de una sesión de inferencia en curso
        if session_id and session_id in self._response_queues:
            await self._response_queues[session_id].put(data)
        else:
            logger.debug(f"Unrouted error (queue already cleaned): {error_msg} (session_id={session_id!r})")

    async def _handle_session_created(self, data: dict, session_id: str | None) -> None:
        if self._session_creation_future and not self._session_creation_future.done():
            self._session_creation_future.set_result(session_id)

    async def _handle_session_error(self, data: dict, session_id: str | None) -> None:
        error_msg = data.get("error", "Unknown session error")
        logger.error(f"Session Error: {error_msg}")
        if self._session_creation_future and not self._session_creation_future.done():
            self._session_creation_future.set_exception(Exception(error_msg))

    async def _handle_list_models_result(self, data: dict, session_id: str | None) -> None:
        future = self._pending_commands.pop("list_models", None)
        if future and not future.done():
            future.set_result(data)
        else:
            logger.warning("Received LIST_MODELS_RESULT but no pending future found.")

    async def _handle_load_model_result(self, data: dict, session_id: str | None) -> None:
        future = self._pending_commands.pop("load_model", None)
        if future and not future.done():
            future.set_result(data)
        else:
            logger.warning("Received LOAD_MODEL_RESULT but no pending future found.")

    async def _handle_session_token(self, data: dict, session_id: str | None) -> None:
        """Fallback: route token/end/abort messages to the session queue."""
        if session_id and session_id in self._response_queues:
            await self._response_queues[session_id].put(data)
        elif data.get("op") not in ("abort", "end"):
            logger.warning(f"Unhandled message op='{data.get('op')}' session_id={session_id!r}")

    # ---------------------------------------------------------------------------
    # Read loop
    # ---------------------------------------------------------------------------

    async def _read_loop(self):
        """
        Reads messages from WebSocket and dispatches them to typed handlers.
        """
        async def _noop(data: dict, session_id) -> None:
            logger.debug(f"Acknowledged op='{data.get('op')}' (no action needed)")

        _handlers = {
            "hello":               self._handle_hello,
            "auth_success":        self._handle_auth_success,
            "error":               self._handle_error,
            "session_created":     self._handle_session_created,
            "session_error":       self._handle_session_error,
            "LIST_MODELS_RESULT":  self._handle_list_models_result,
            "list_models_result":  self._handle_list_models_result,
            "LOAD_MODEL_RESULT":   self._handle_load_model_result,
            "load_model_result":   self._handle_load_model_result,
            # Acks del Engine que no requieren acción
            "context_set":         _noop,
            "context_error":       _noop,
            "session_closed":      _noop,
        }

        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    op = data.get("op")
                    session_id = data.get("session_id")

                    handler = _handlers.get(op, self._handle_session_token)
                    await handler(data, session_id)

                except json.JSONDecodeError:
                    logger.error("Failed to decode JSON message")
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed in read loop.")
            raise  # Propagate to connection loop

    async def create_session(self) -> str:
        """
        Requests a new session ID from the engine.
        """
        if not self.is_connected:
            raise Exception("Inference Engine not connected")

        async with self.lock:
             self._session_creation_future = asyncio.Future()
             try:
                 await self.websocket.send(json.dumps({"op": "create_session"}))
                 return await asyncio.wait_for(self._session_creation_future, timeout=settings.INFERENCE_SESSION_TIMEOUT)
             finally:
                 self._session_creation_future = None

    async def abort_session(self, session_id: str):
        """
        Sends abort signal for a specific session.
        """
        if self.is_connected:
             try:
                 await self.websocket.send(json.dumps({
                     "op": "abort",
                     "session_id": session_id
                 }))
                 logger.info(f"Aborted session {session_id}")
             except Exception as e:
                 logger.error(f"Failed to abort session {session_id}: {e}")

    async def close_session(self, session_id: str):
        """
        Closes and frees the session from the InferenceCenter.
        """
        if self.is_connected:
             try:
                 await self.websocket.send(json.dumps({
                     "op": "close_session",
                     "session_id": session_id
                 }))
                 logger.info(f"Closed session {session_id}")
             except Exception as e:
                 logger.error(f"Failed to close session {session_id}: {e}")

    async def ensure_session(self, user_id: str) -> str:
        """
        Creates a fresh session for a user, closing any existing one first.
        Tracks active sessions to avoid leaving dangling resources.
        """
        old_session = self._user_sessions.get(user_id)
        if old_session:
            logger.info(f"Closing previous session {old_session} for user {user_id}")
            await self.close_session(old_session)
        
        session_id = await self.create_session()
        self._user_sessions[user_id] = session_id
        logger.info(f"New session {session_id} assigned to user {user_id}")
        return session_id

    async def set_context(self, session_id: str, messages: list):
        """
        Sends conversation history to the InferenceCenter for context recovery.
        Must be called after create_session and before infer.
        """
        if not self.is_connected:
            raise Exception("Inference Engine not connected")
        
        payload = {
            "op": "set_context",
            "session_id": session_id,
            "context": {
                "messages": messages
            }
        }
        await self.websocket.send(json.dumps(payload))
        logger.info(f"Context set for session {session_id} ({len(messages)} messages)")

    async def release_session(self, user_id: str):
        """
        Closes and unregisters a user's active session.
        Called on client disconnect to free InferenceCenter resources.
        """
        session_id = self._user_sessions.pop(user_id, None)
        if session_id:
            logger.info(f"Releasing session {session_id} for user {user_id}")
            await self.close_session(session_id)
    
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
                f"[TRACE] Sending COMMAND_LOAD_MODEL to engine \u2014 model_id={model_id!r} "
                f"(current_engine_model before={self.current_engine_model!r})"
            )
            await self.websocket.send(json.dumps({
                "op": "COMMAND_LOAD_MODEL",
                "model_id": model_id
            }))

            result = await asyncio.wait_for(future, timeout=settings.INFERENCE_LOAD_MODEL_TIMEOUT)
            logger.info(f"[TRACE] LOAD_MODEL_RESULT from engine \u2014 raw={result!r}")
            success = result.get("status") == "SUCCESS"
            if success:
                self.current_engine_model = model_id
                logger.info(
                    f"[TRACE] \u2705 Model loaded \u2014 current_engine_model={self.current_engine_model!r} \u2014 IN SYNC"
                )
            else:
                logger.error(f"[TRACE] \u274c Failed to load model {model_id!r}: {result}")
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
                                    yield f"\n[Error parsing tool call: {e}]\n"
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
