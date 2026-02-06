import asyncio
import websockets
import json
import logging
from src.core.config import settings
from src.core.events import event_bus

logger = logging.getLogger(__name__)

class TranscriptionClient:
    def __init__(self):
        self.url = settings.TRANSCRIPTION_SERVICE_URL
        self.running = False

    async def connect_and_listen(self):
        """
        Connects to the transcription service and listens for incoming text.
        Retries connection on failure.
        """
        self.running = True
        while self.running:
            try:
                logger.info(f"Connecting to Transcription Service at {self.url}...")
                async with websockets.connect(self.url) as websocket:
                    logger.info("Connected to Transcription Service.")
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            # Assuming the server sends {"text": "..."} or similar
                            # Adapting based on raw text or json. 
                            # If it's just raw string from some servers, handle that too.
                            # For now assuming JSON structure based on standard practices.
                            text = data.get("text", "")
                            if text:
                                await event_bus.publish({
                                    "type": "transcription_input",
                                    "content": text,
                                    "source": "transcription_service"
                                })
                        except json.JSONDecodeError:
                            logger.warning(f"Received non-JSON message: {message}")
            except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError) as e:
                logger.error(f"Connection to Transcription Service lost: {e}. Retrying in 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected error in Transcription Client: {e}")
                await asyncio.sleep(5)

    def stop(self):
        self.running = False

transcription_client = TranscriptionClient()
