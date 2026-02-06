import logging
from src.core.events import event_bus
from src.core.memory import memory_manager
from src.services.inference import inference_client

logger = logging.getLogger(__name__)

class JotaController:
    def __init__(self):
        # Subscribe to input events
        event_bus.subscribe(self.handle_input)

    async def handle_input(self, event: dict):
        """
        Main logic handler.
        1. Receive text (from STT or API).
        2. Retrieve context from Memory.
        3. Send to Inference Engine.
        4. Log/Handle Response.
        """
        source = event.get("source")
        content = event.get("content")
        session_id = event.get("session_id", "default")

        logger.info(f"Received input from {source}: {content}")

        # 1. Update Memory (User Input)
        await memory_manager.add_message(session_id, "user", content)

        # 2. Get Context
        context = await memory_manager.get_recent_context(session_id)

        # 3. Call Inference
        try:
            logger.info("Sending to Inference Engine...")
            response = await inference_client.infer(content, context)
            logger.info(f"Inference Response: {response}")

            # 4. Update Memory (Assistant Output)
            await memory_manager.add_message(session_id, "assistant", response)

        except Exception as e:
            logger.error(f"Error during inference flow: {e}")

jota_controller = JotaController()
