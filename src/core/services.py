import logging
from src.core.memory import MemoryManager
from src.services.inference import InferenceClient
from src.core.controller import JotaController

logger = logging.getLogger(__name__)

# Instantiate Singleton Services
memory_manager = MemoryManager()
inference_client = InferenceClient(memory_manager=memory_manager)
jota_controller = JotaController(inference_client=inference_client)

async def shutdown_services():
    """
    Graceful shutdown of all services.
    """
    logger.info("Shutting down services...")
    await inference_client.invoke_shutdown()
    await memory_manager.close()
    logger.info("Services shut down.")
