"""
mqtt.py
~~~~~~~
MQTTService: connects to Mosquitto broker, subscribes to voice transcription
topic, routes each message through JotaController (stateless), and publishes
the response back to a per-client topic.

Message format (subscribe):  {"client_id": "...", "text": "..."}
Response format (publish):   {"client_id": "...", "text": "..."}
Response topic:              {MQTT_RESPONSE_TOPIC_PREFIX}/{client_id}
"""
import asyncio
import json
import logging
from uuid import uuid4

import aiomqtt

from src.core.config import settings

logger = logging.getLogger(__name__)

_RECONNECT_BASE_DELAY = 2.0   # seconds
_RECONNECT_MAX_DELAY = 60.0   # seconds


class MQTTService:
    def __init__(self, inference_client, jota_controller):
        self._inference_client = inference_client
        self._controller = jota_controller
        self._task: asyncio.Task | None = None

    async def connect(self) -> None:
        """Start background MQTT listener loop."""
        self._task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self) -> None:
        """Connect to broker, subscribe, and process messages — with reconnect backoff."""
        delay = _RECONNECT_BASE_DELAY
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=settings.MQTT_BROKER_HOST,
                    port=settings.MQTT_BROKER_PORT,
                    username=settings.MQTT_USERNAME,
                    password=settings.MQTT_PASSWORD,
                    identifier=settings.MQTT_CLIENT_ID,
                    keepalive=settings.MQTT_KEEPALIVE,
                ) as client:
                    delay = _RECONNECT_BASE_DELAY  # reset on successful connect
                    logger.info(
                        f"MQTT connected — broker={settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}"
                    )
                    await client.subscribe(settings.MQTT_SUBSCRIBE_TOPIC, qos=settings.MQTT_QOS)
                    logger.info(f"MQTT subscribed to '{settings.MQTT_SUBSCRIBE_TOPIC}'")

                    async for message in client.messages:
                        asyncio.create_task(self._handle_message(client, message))

            except aiomqtt.MqttError as e:
                logger.warning(f"MQTT disconnected: {e}. Reconnecting in {delay:.0f}s...")
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RECONNECT_MAX_DELAY)
            except asyncio.CancelledError:
                logger.info("MQTT listener loop cancelled.")
                raise

    async def _handle_message(self, client: aiomqtt.Client, message) -> None:
        """Parse JSON payload, call controller, publish response."""
        try:
            data = json.loads(message.payload)
            client_id = data["client_id"]
            text = data["text"]
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning(f"MQTT: Invalid message on {message.topic}: {message.payload!r}")
            return

        logger.info(f"MQTT: Received from client_id={client_id!r}: {text!r}")
        response_text = await self._process(client_id, text)

        response_payload = json.dumps({"client_id": client_id, "text": response_text})
        response_topic = f"{settings.MQTT_RESPONSE_TOPIC_PREFIX}/{client_id}"
        await client.publish(response_topic, response_payload, qos=settings.MQTT_QOS)
        logger.info(f"MQTT: Published response to '{response_topic}'")

    async def _process(self, client_id: str, text: str) -> str:
        """Create ephemeral inference session, run stateless inference, collect response."""
        session_id = await self._inference_client.create_session()
        try:
            tokens = []
            async for token in self._controller.handle_input({
                "content": text,
                "session_id": session_id,
                "conversation_id": str(uuid4()),  # ephemeral — no history loaded
                "user_id": client_id,
                "client_id": client_id,
                "model_id": None,
                "stateless": True,
                "system_prompt_override": settings.MQTT_CLIENT_SYSTEM_PROMPT,
            }):
                if isinstance(token, str):
                    tokens.append(token)
                # Skip status dicts (tool status messages)
            return "".join(tokens).strip()
        finally:
            await self._inference_client.close_session(session_id)

    async def shutdown(self) -> None:
        """Cancel the background listener task and wait for it to exit."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MQTT service shut down.")
