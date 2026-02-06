import asyncio
import websockets
import json
import logging
from src.core.config import settings

logger = logging.getLogger(__name__)

class InferenceClient:
    def __init__(self):
        self.url = settings.INFERENCE_SERVICE_URL
        self.websocket = None
        self.lock = asyncio.Lock()

    async def connect(self):
        """
        Establishes connection to the Inference Engine.
        """
        try:
            self.websocket = await websockets.connect(self.url)
            logger.info(f"Connected to Inference Engine at {self.url}")
        except Exception as e:
            logger.error(f"Failed to connect to Inference Engine: {e}")
            raise e

    async def infer(self, prompt: str, session_context: str) -> str:
        """
        Sends an inference request and awaits the full response.
        Handles checking for connection and reconnecting if needed.
        Encrypts requests with a lock to prevent concurrent websocket reads.
        """
        async with self.lock:
            if self.websocket is None:
                await self.connect()

            request = {
                "opcode": "infer",
                "prompt": prompt,
                "context": session_context
            }
            
            try:
                await self.websocket.send(json.dumps(request))
            except (websockets.exceptions.ConnectionClosed, AttributeError):
                # Reconnect and retry once
                logger.info("Connection lost, reconnecting...")
                await self.connect()
                await self.websocket.send(json.dumps(request))
            
            full_response = ""
            try:
                async for message in self.websocket:
                    try:
                        data = json.loads(message)
                        opcode = data.get("opcode")
                        
                        if opcode == "token":
                            token = data.get("content", "")
                            full_response += token
                        elif opcode == "end":
                            break
                        elif opcode == "error":
                            logger.error(f"Inference Error: {data.get('content')}")
                            break
                    except json.JSONDecodeError:
                        continue
            except websockets.exceptions.ConnectionClosed as e:
                logger.error(f"Connection closed during inference: {e}")
                
            return full_response

inference_client = InferenceClient()
