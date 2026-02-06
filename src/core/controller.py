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
        # Note: Event bus is primarily for fire-and-forget or decoupled logic.
        # For direct streaming response (API -> Controller -> API), we might call handle_input directly.
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
        2. Retrieve context.
        3. Stream from Inference Engine.
        4. Log/Handle Response.
        """
        content = payload.get("content")
        session_id = payload.get("session_id", "default")
        # Logic for user identification can be enhanced. 
        # Using session_id as user_id for inference client for now.
        user_id = session_id 

        logger.info(f"Controller processing input for {user_id}: {content}")

        # 1. Update Memory (User Input)
        await memory_manager.add_message(session_id, "user", content)

        # 2. Get Context (Optional: could be passed to infer if client supported it)
        # For now, memory manager handles history, but we might want to fetch it 
        # to construct the prompt if the Inference Engine was stateless.
        # Since Inference Engine is stateful (sessions), we just send the prompt.
        
        # 3. Call Inference & Stream
        full_response = ""
        try:
            logger.info("Streaming from Inference Engine...")
            async for token in inference_client.infer(user_id, content):
                full_response += token
                yield token
            
            logger.info("Inference stream complete.")

            # 4. Update Memory (Assistant Output)
            await memory_manager.add_message(session_id, "assistant", full_response)

        except Exception as e:
            logger.error(f"Error during inference flow: {e}")
            yield f" [Error: {str(e)}]"

jota_controller = JotaController()
