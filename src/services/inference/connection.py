"""
Low-level WebSocket connection management.

Provides `InferenceConnectionMixin`, handling the raw WebSocket connection to the
InferenceCenter, including connection retries, SSL wrapping, token authentication,
and basic message dispatching.
"""
import asyncio
import ssl
import websockets
import json
import logging

from src.core.config import settings
from .exceptions import InferenceEngineBusyError, ModelNotFoundError

logger = logging.getLogger(__name__)

class InferenceConnectionMixin:
    """
    Mixin para manejar la conexión WebSocket de bajo nivel con el InferenceCenter.
    """

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
