import asyncio
import websockets
import json
import logging
import ssl
from typing import Dict, AsyncGenerator, Any, Optional

from src.core.config import settings
from src.core.memory import MemoryManager

logger = logging.getLogger(__name__)

class InferenceClient:
    def __init__(self, memory_manager: MemoryManager, url: str = None, client_id: str = None, api_key: str = None):
        self.url = url or settings.INFERENCE_SERVICE_URL
        self.client_id = client_id or settings.INFERENCE_CLIENT_ID
        self.api_key = api_key or settings.INFERENCE_API_KEY
        self.memory_manager = memory_manager
        
        self.websocket = None
        self.lock = asyncio.Lock()
        
        self.active_sessions: Dict[str, str] = {}
        self._response_queues: Dict[str, asyncio.Queue] = {}
        self._pending_sessions: Dict[str, asyncio.Future] = {} 
        self._session_creation_future: Optional[asyncio.Future] = None
        self._auth_future: Optional[asyncio.Future] = None
        
        # Background tasks
        self._connection_task = None
        self._shutdown_event = asyncio.Event()

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
        return self.websocket is not None and self.websocket.open

    async def _connection_loop(self):
        """
        Maintains connection to the Inference Engine with exponential backoff.
        Supports SSL/TLS and Auth Handshake.
        """
        backoff_delay = 1
        max_backoff = 60

        while not self._shutdown_event.is_set():
            try:
                logger.info(f"Connecting to Message Engine at {self.url}")
                
                # Configure SSL Context if needed (HEAD logic)
                ssl_context = None
                if self.url.startswith("wss://"):
                    ssl_context = ssl.create_default_context()
                    if not settings.SSL_VERIFY:
                        logger.warning("SSL Verification disabled for InferenceClient")
                        ssl_context.check_hostname = False
                        ssl_context.verify_mode = ssl.CERT_NONE
                
                async with websockets.connect(self.url, ssl=ssl_context) as websocket:
                    self.websocket = websocket
                    backoff_delay = 1 # Reset backoff on successful connection
                    
                    # Authenticate (HEAD logic + Remote flow)
                    self._auth_future = asyncio.Future()
                    
                    auth_payload = {
                        "op": "auth",
                        "client_id": self.client_id,
                        "api_key": self.api_key,
                        "jota_db_url": settings.JOTA_DB_URL
                    }
                    
                    # Start read loop as a task so we can wait for auth
                    read_task = asyncio.create_task(self._read_loop())
                    
                    await websocket.send(json.dumps(auth_payload))
                    logger.info("Sent authentication credentials. Waiting for confirmation...")
                    
                    # Wait for Auth Success (HEAD logic)
                    try:
                        await asyncio.wait_for(self._auth_future, timeout=10.0)
                        logger.info("Authenticated with Inference Engine")
                    except (asyncio.TimeoutError, Exception) as e:
                        logger.error(f"Authentication failed: {e}")
                        read_task.cancel()
                        raise # Trigger retry loop
                    finally:
                         self._auth_future = None
                    
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

    async def _read_loop(self):
        """
        Reads messages from WebSocket.
        """
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    op = data.get("op")
                    session_id = data.get("session_id")
                    
                    # logger.debug(f"📨 Received message: op={op}, session_id={session_id}")
                    
                    if op == "hello":
                        logger.info(f"Received hello: {data.get('message', 'ready')}")
                        
                    elif op == "auth_success":
                        logger.info(f"Auth Success: {data}")
                        if self._auth_future and not self._auth_future.done():
                            self._auth_future.set_result(True)
                            
                    elif op == "error":
                        error_msg = data.get("message", "Unknown error")
                        logger.error(f"Server Error: {error_msg}")
                        # If authenticating, fail it
                        if self._auth_future and not self._auth_future.done():
                            self._auth_future.set_exception(Exception(error_msg))
                            return 
                        
                        # Propagate to sessions
                        if session_id and session_id in self._response_queues:
                            await self._response_queues[session_id].put(data)
                            
                    elif op == "session_created":
                        if self._session_creation_future and not self._session_creation_future.done():
                            self._session_creation_future.set_result(session_id)
                    
                    elif session_id and session_id in self._response_queues:
                        await self._response_queues[session_id].put(data)
                        
                    elif op in ["hello", "auth_success"]:
                        pass # Handled above
                        
                    else:
                        logger.warning(f"Unhandled message: {op}")

                except json.JSONDecodeError:
                    logger.error("Failed to decode JSON message")
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed in read loop.")
            raise # Propagate to connection loop

    async def create_session(self) -> str:
        """
        Requests a new session ID from the engine.
        """
        if not self.websocket or not self.websocket.open:
            raise Exception("Inference Engine not connected")

        async with self.lock:
             self._session_creation_future = asyncio.Future()
             try:
                 await self.websocket.send(json.dumps({"op": "create_session"}))
                 return await asyncio.wait_for(self._session_creation_future, timeout=5.0)
             finally:
                 self._session_creation_future = None

    async def abort_session(self, session_id: str):
        """
        Sends abort signal for a specific session.
        """
        if self.websocket and self.websocket.open:
             try:
                 await self.websocket.send(json.dumps({
                     "op": "abort",
                     "session_id": session_id
                 }))
                 logger.info(f"Aborted session {session_id}")
             except Exception as e:
                 logger.error(f"Failed to abort session {session_id}: {e}")

    async def infer(self, session_id: str, prompt: str, conversation_id: str, params: Optional[Dict[str, Any]] = None) -> AsyncGenerator[str, None]:
        # Using Remote's robust implementation
        if params is None:
            params = {"temp": 0.7}
            
        log_prefix = f"[Conv: {conversation_id}][Sess: {session_id}]"
        response_buffer = []

        try:
            logger.info(f"{log_prefix} Starting inference...")
            if session_id not in self._response_queues:
                self._response_queues[session_id] = asyncio.Queue()
            
            request = {
                "op": "infer",
                "session_id": session_id,
                "prompt": prompt,
                "params": params
            }
            
            if not self.websocket or not self.websocket.open:
                 raise Exception("Inference Engine Unavailable")

            await self.websocket.send(json.dumps(request))
            
            queue = self._response_queues[session_id]
            
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0) 
                except asyncio.TimeoutError:
                    raise Exception("Inference timed out waiting for token")

                if data is None: 
                     raise Exception("Stream interrupted")
                    
                op = data.get("op")
                
                if op == "token":
                    content = data.get("content", "")
                    response_buffer.append(content)
                    yield content
                elif op == "end":
                    full_response = "".join(response_buffer)
                    await self.memory_manager.save_message(conversation_id, "assistant", full_response)
                    logger.info(f"{log_prefix} Inference complete.")
                    break
                elif op == "error":
                    error_msg = data.get("content")
                    raise Exception(error_msg)
            
        except Exception as e:
            logger.error(f"{log_prefix} Inference error: {e}")
            
            if response_buffer:
                logger.info(f"{log_prefix} Saving interrupted response.")
                partial_response = "".join(response_buffer) + " [INTERRUPTED]"
                await self.memory_manager.save_message(conversation_id, "assistant", partial_response)
            
            await self.memory_manager.mark_conversation_error(conversation_id)
            raise e
        finally:
             if session_id in self._response_queues:
                 del self._response_queues[session_id]
             logger.debug(f"{log_prefix} Cleaned up queue.")
