import logging
from src.core.memory import MemoryManager
from src.services.inference import InferenceClient
from src.core.controller import JotaController
from src.services.mqtt import MQTTService
import src.tools  # noqa: F401 — triggers @tool decorator registrations

logger = logging.getLogger(__name__)

# Instantiate Singleton Services
memory_manager = MemoryManager()
inference_client = InferenceClient(memory_manager=memory_manager)
jota_controller = JotaController(inference_client=inference_client, memory_manager=memory_manager)
mqtt_service = MQTTService(
    inference_client=inference_client,
    jota_controller=jota_controller,
)

async def shutdown_services():
    """
    Graceful shutdown of all services.
    """
    logger.info("Shutting down services...")
    await mqtt_service.shutdown()
    await inference_client.invoke_shutdown()
    await memory_manager.close()
    logger.info("Services shut down.")
