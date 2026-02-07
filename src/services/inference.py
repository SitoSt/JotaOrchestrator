import asyncio
import websockets
import json
import logging
from typing import Dict, AsyncGenerator, Any, Optional

from src.core.config import settings

logger = logging.getLogger(__name__)

class InferenceClient:
    def __init__(self, url: str = None, client_id: str = None, api_key: str = None):
        self.url = url or settings.INFERENCE_SERVICE_URL
        self.client_id = client_id or settings.INFERENCE_CLIENT_ID
        self.api_key = api_key or settings.INFERENCE_API_KEY
        
        self.websocket = None
        self.lock = asyncio.Lock()
        
        # Maps user_id -> session_id
        self.active_sessions: Dict[str, str] = {}
        
        # Track pending session creation events
        # key: request_id (or temporary marker), value: asyncio.Future
        self._pending_sessions: Dict[str, asyncio.Future] = {} 

    async def connect(self):
        """
        Establishes connection to the Inference Engine and authenticates.
        """
        try:
            # Connect only if not already connected
            if self.websocket and self.websocket.open:
                return

            logger.info(f"Connecting to Inference Engine at {self.url}")
            self.websocket = await websockets.connect(self.url)
            
            # 1. Authenticaton
            auth_payload = {
                "op": "auth",
                "client_id": self.client_id,
                "api_key": self.api_key
            }
            await self.websocket.send(json.dumps(auth_payload))
            logger.info("Sent authentication credentials")
            
            # Start background listener for unsolicited messages and concurrent request handling.
            # A reader loop is required to dispatch incoming tokens to the correct session queue
            # while allowing the 'infer' method to yield results in real-time.
            self._response_queues: Dict[str, asyncio.Queue] = {}  # session_id -> Queue
            self._reader_task = asyncio.create_task(self._read_loop())
            
        except Exception as e:
            logger.error(f"Failed to connect to Inference Engine: {e}")
            self.websocket = None
            raise e

    async def _read_loop(self):
        """
        Continuously reads messages from the WebSocket and dispatches them.
        """
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    op = data.get("op")
                    session_id = data.get("session_id")
                    
                    if op == "session_created":
                        # Handle session creation response.
                        if self._session_creation_future and not self._session_creation_future.done():
                             self._session_creation_future.set_result(session_id)

                    elif session_id and session_id in self._response_queues:
                        # Dispatch to the specific session's queue
                        await self._response_queues[session_id].put(data)
                    else:
                        logger.warning(f"Received unhandled message: {data}")

                except json.JSONDecodeError:
                    logger.error(f"Failed to decode message: {message}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    
        except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
            logger.info("WebSocket connection closed")
            # Cleanup queues
            for q in self._response_queues.values():
                await q.put(None) # Signal end
        finally:
            self.websocket = None

    async def get_session(self, user_id: str) -> str:
        """
        Retrieves an existing session ID or creates a new one for the user.
        Ensures atomic session creation.
        """
        async with self.lock:
            # Check if user already has a session
            if user_id in self.active_sessions:
                return self.active_sessions[user_id]
            
            # Connect if needed
            if not self.websocket or not self.websocket.open:
                await self.connect()

            # Create new session - Serialize this op to map response correctly
            self._session_creation_future = asyncio.Future()
            
            try:
                await self.websocket.send(json.dumps({"op": "create_session"}))
                
                # Wait for the response (timeout 5s)
                session_id = await asyncio.wait_for(self._session_creation_future, timeout=5.0)
                
                self.active_sessions[user_id] = session_id
                logger.info(f"Created session {session_id} for user {user_id}")
                return session_id
                
            except asyncio.TimeoutError:
                logger.error("Timeout waiting for session creation")
                raise Exception("Failed to create inference session: Timeout")
            finally:
                self._session_creation_future = None

    async def infer(self, user_id: str, prompt: str, params: Optional[Dict[str, Any]] = None) -> AsyncGenerator[str, None]:
        """
        Sends an inference request and yields tokens in real-time.
        Handles reconnection automatically.
        """
        if params is None:
            params = {"temp": 0.7}

        retries = 1
        while retries >= 0:
            try:
                # Get valid session
                session_id = await self.get_session(user_id)
                
                # Setup queue for this session
                if session_id not in self._response_queues:
                    self._response_queues[session_id] = asyncio.Queue()
                
                # Send inference request
                request = {
                    "op": "infer",
                    "session_id": session_id,
                    "prompt": prompt,
                    "params": params
                }
                
                if not self.websocket or not self.websocket.open:
                     # Force reconnect if socket died in background
                     await self.connect()

                await self.websocket.send(json.dumps(request))
                
                # Stream responses
                queue = self._response_queues[session_id]
                
                while True:
                    data = await queue.get()
                    
                    if data is None: # Connection died
                        raise websockets.exceptions.ConnectionClosed(1006, "Internal Signal")
                        
                    op = data.get("op")
                    
                    if op == "token":
                        yield data.get("content", "")
                    elif op == "end":
                        # Usage stats could be handled here
                        break
                    elif op == "error":
                        logger.error(f"Inference Error: {data.get('content')}")
                        raise Exception(data.get("content"))
                
                return # Successful completion

            except (websockets.exceptions.ConnectionClosed, Exception) as e:
                logger.warning(f"Inference interrupted: {e}. Retrying...")
                retries -= 1
                self.websocket = None # Force reconnect logic in get_session -> connect
                
                # Clean up logic on failure.
                # If connection drops, we attempt to reconnect (retries > 0).
                # Session validity is uncertain on reconnect, but we attempt reuse. 
                # Ideally, the server preserves sessions or we might need to invalidate 'active_sessions'.

                
                if retries < 0:
                     logger.error("Max retries exceeded for inference.")
                     raise e

    # Ensure to cancel reader task on shutdown
    async def invoke_shutdown(self):
        if hasattr(self, '_reader_task'):
             self._reader_task.cancel()

inference_client = InferenceClient()
