import logging
import asyncio
from typing import AsyncGenerator
from src.core.events import event_bus
from src.core.memory import memory_manager
from src.services.inference import inference_client

logger = logging.getLogger(__name__)

class JotaController:
    def __init__(self):
        # Subscribe to input events
        # Subscribe to input events for async/decoupled processing.
        event_bus.subscribe(self.process_event_async)

    async def process_event_async(self, event: dict):
        """
        Wrapper to process events subscribed via event_bus.
        Since event_bus probably expects coroutines but doesn't handle generators,
        we drain the generator here if it's called via event bus.
        """
        async for _ in self.handle_input(event):
            pass

    async def handle_input(self, payload: dict) -> AsyncGenerator[str, None]:
        """
        Main logic handler (Generator).
        1. Receive text.
        2. Stream from Inference Engine.
        """
        content = payload.get("content")
        session_id = payload.get("session_id")
        conversation_id = payload.get("conversation_id")
        
        if not session_id or not conversation_id:
             logger.error("Missing session_id or conversation_id in payload")
             yield " [Error: Internal Context Missing]"
             return

        logger.info(f"Controller processing input for session {session_id}")

        # Note: User message is already saved by the API layer (chat.py).
        
        # Call Inference & Stream
        try:
            logger.info("Streaming from Inference Engine...")
            async for token in inference_client.infer(session_id, content, conversation_id):
                yield token
            
            logger.info("Inference stream complete.")
            # Note: Assistant message is saved by InferenceClient on "end" op.

        except Exception as e:
            logger.error(f"Error during inference flow: {e}")
            yield f" [Error: {str(e)}]"

jota_controller = JotaController()
