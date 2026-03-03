"""
controller.py
~~~~~~~~~~~~~
Orquesta el flujo de entrada de usuario hacia el InferenceCenter.

Responsabilidades:
  - Verificar que el modelo configurado para la conversación esté cargado
    en el InferenceCenter antes de cada inferencia.
  - Delegar el streaming de tokens al InferenceClient.
  - Actuar como suscriptor del event_bus para procesamiento desacoplado.
"""
import asyncio
import logging
from typing import AsyncGenerator, TYPE_CHECKING

from src.core.events import event_bus
from src.services.inference import InferenceClient, InferenceEngineBusyError, ModelNotFoundError

if TYPE_CHECKING:
    from src.core.memory import MemoryManager

logger = logging.getLogger(__name__)

_LOAD_MAX_RETRIES = 3
_LOAD_BASE_DELAY = 1.0  # segundos


class JotaController:
    """
    Controlador principal del Orchestrator.

    Args:
        inference_client: Cliente WebSocket con el InferenceCenter.
        memory_manager:   Acceso a JotaDB para leer metadatos de conversaciones.
    """

    def __init__(self, inference_client: InferenceClient, memory_manager: "MemoryManager"):
        self.inference_client = inference_client
        self.memory_manager = memory_manager
        # Suscribir al event_bus para procesamiento desacoplado
        event_bus.subscribe(self.process_event_async)

    async def process_event_async(self, event: dict):
        """
        Wrapper para el event_bus: drena el generator de handle_input.
        """
        async for _ in self.handle_input(event):
            pass

    async def switch_model(self, conversation_id: str, client_id, model_id: str) -> None:
        """
        Cambia el modelo activo de forma atómica: primero lo carga en el Engine
        y solo si el Engine confirma SUCCESS actualiza la DB.

        Es la única fuente de verdad para cambios de modelo. Se usa en:
          - Reconexión WS con nuevo model_id (chat.py)
          - Comandos de cambio de modelo en mitad de sesión (chat.py WS loop)
          - _ensure_model_loaded cuando detecta un mismatch engine ↔ DB

        Args:
            conversation_id: ID de la conversación a actualizar.
            client_id:       ID del cliente propietario de la conversación.
            model_id:        Modelo destino a cargar.

        Raises:
            ModelNotFoundError:      Si el modelo no existe en el catálogo del Engine.
            InferenceEngineBusyError: Si el Engine sigue ocupado tras todos los reintentos.
            RuntimeError:            Si la carga falla por razón desconocida.
        """
        logger.info(
            f"[TRACE][Conv: {conversation_id}] switch_model called — "
            f"target={model_id!r} engine_current={self.inference_client.current_engine_model!r}"
        )

        if self.inference_client.current_engine_model == model_id:
            # El engine ya tiene el modelo — solo aseguramos que la DB esté en sync.
            await self.memory_manager.set_conversation_model(conversation_id, client_id, model_id)
            logger.info(
                f"[TRACE][Conv: {conversation_id}] ✅ Model already active: {model_id!r}. "
                f"DB synced, no engine switch needed."
            )
            return

        # — Validación de existencia pre-carga (falla rápida) —
        try:
            available = await self.inference_client.list_models()
            if isinstance(available, list) and available:
                ids = [m.get("id") or m.get("model_id") or m for m in available]
                if model_id not in ids:
                    logger.error(f"[TRACE][Conv: {conversation_id}] Model {model_id!r} not in Engine catalog: {ids}")
                    raise ModelNotFoundError(f"Model '{model_id}' not found in Engine catalog")
                logger.info(
                    f"[TRACE][Conv: {conversation_id}] Model {model_id!r} confirmed in Engine catalog ({len(ids)} models)."
                )
        except ModelNotFoundError:
            raise
        except Exception as e:
            logger.warning(f"[TRACE][Conv: {conversation_id}] Could not validate catalog (proceeding anyway): {e}")

        # — Carga con backoff exponencial —
        logger.info(
            f"[TRACE][Conv: {conversation_id}] ⚠️ Sending COMMAND_LOAD_MODEL — "
            f"active={self.inference_client.current_engine_model!r} → target={model_id!r}"
        )

        delay = _LOAD_BASE_DELAY
        success = False
        for attempt in range(1, _LOAD_MAX_RETRIES + 1):
            try:
                success = await self.inference_client.load_model(model_id)
                break
            except InferenceEngineBusyError:
                if attempt == _LOAD_MAX_RETRIES:
                    logger.error(f"[TRACE][Conv: {conversation_id}] Engine busy after {_LOAD_MAX_RETRIES} retries. Giving up.")
                    raise
                logger.warning(
                    f"[TRACE][Conv: {conversation_id}] Engine busy (attempt {attempt}/{_LOAD_MAX_RETRIES}). "
                    f"Retrying in {delay:.0f}s..."
                )
                await asyncio.sleep(delay)
                delay *= 2

        if success:
            # Atomicidad: DB solo se actualiza tras confirmación del Engine.
            await self.memory_manager.set_conversation_model(conversation_id, client_id, model_id)
            logger.info(
                f"[TRACE][Conv: {conversation_id}] ✅ switch_model OK — "
                f"engine_model={self.inference_client.current_engine_model!r} "
                f"db_model={model_id!r} — IN SYNC"
            )
        else:
            raise RuntimeError(
                f"Failed to load model '{model_id}' for conversation {conversation_id}"
            )

    async def _ensure_model_loaded(self, conversation_id: str, client_id) -> None:
        """
        Verifica antes de cada inferencia que el modelo de la DB esté cargado en el Engine.
        Delega a switch_model si detecta un mismatch.

        Raises:
            ModelNotFoundError:      propagado desde switch_model.
            InferenceEngineBusyError: propagado desde switch_model.
            RuntimeError:            propagado desde switch_model.
        """
        conversation = await self.memory_manager.get_conversation(conversation_id, client_id)
        if not conversation:
            logger.warning(f"Could not fetch conversation {conversation_id} to check model.")
            return

        required_model = conversation.get("model_id")
        if not required_model:
            logger.debug(f"Conversation {conversation_id} has no model_id set. Skipping model check.")
            return

        logger.info(
            f"[TRACE][Conv: {conversation_id}] _ensure_model_loaded — "
            f"db_model={required_model!r} engine_current={self.inference_client.current_engine_model!r}"
        )

        if self.inference_client.current_engine_model == required_model:
            logger.info(
                f"[TRACE][Conv: {conversation_id}] ✅ Model already active: {required_model!r}. No switch needed."
            )
            return

        # Mismatch detectado — switch_model es la única fuente de verdad para cambios de modelo.
        await self.switch_model(conversation_id, client_id, required_model)

    async def handle_input(self, payload: dict) -> AsyncGenerator[str, None]:
        """
        Flujo principal por petición:
          1. Verificar y cargar el modelo de la conversación si es necesario.
          2. Hacer streaming de tokens desde el InferenceCenter.

        Error handling diferenciado:
          - ModelNotFoundError      → marca conversación en error; no permite más prompts.
          - InferenceEngineBusyError → error transitorio; NO marca conversación en error.
          - Otros errores           → propaga el mensaje de error al cliente.
        """
        content = payload.get("content")
        session_id = payload.get("session_id")
        conversation_id = payload.get("conversation_id")
        user_id = payload.get("user_id")
        client_id = payload.get("client_id")
        model_id = payload.get("model_id")

        if not session_id or not conversation_id or not user_id:
            logger.error("Missing session_id, conversation_id, or user_id in payload")
            yield " [Error: Internal Context Missing]"
            return

        logger.info(f"Controller processing input for session {session_id}")

        try:
            # Pre-infer: garantizar que el modelo correcto está cargado
            await self._ensure_model_loaded(conversation_id, client_id)

            # Usar el modelo activo real (puede haber sido actualizado por _ensure_model_loaded)
            effective_model = self.inference_client.current_engine_model or model_id
            
            from src.core.tool_manager import tool_manager
            import time as _time
            import json as _json
            tool_instructions = tool_manager.get_system_prompt_addition()
            
            full_prompt = content
            if tool_instructions:
                full_prompt = f"[SYSTEM INSTRUCTIONS]\n{tool_instructions}\n[/SYSTEM INSTRUCTIONS]\n\nUser: {content}"

            logger.info(
                f"[TRACE][Conv: {conversation_id}] Calling infer \u2014 "
                f"effective_model={effective_model!r} "
                f"engine_current={self.inference_client.current_engine_model!r}"
            )
            
            tool_executed = False
            pre_tool_thinking = []   # Buffer for text emitted BEFORE the tool call
            
            async for token in self.inference_client.infer(
                session_id=session_id,
                prompt=full_prompt,
                conversation_id=conversation_id,
                user_id=user_id,
                params=None,
                client_id=client_id,
                model_id=effective_model,
            ):
                if isinstance(token, dict) and token.get("type") == "tool_call":
                    tc_payload = token.get("payload", {})
                    tool_name = tc_payload.get("name")
                    tool_args = tc_payload.get("arguments", {})
                    
                    # Save the model's pre-tool thinking to the DB for traceability,
                    # but DO NOT yield it to the user.
                    if pre_tool_thinking:
                        thinking_text = "".join(pre_tool_thinking)
                        await self.memory_manager.save_message(
                            conversation_id=conversation_id,
                            user_id=user_id,
                            role="assistant",
                            content=thinking_text,
                            client_id=client_id,
                            metadata={"model_id": effective_model, "thinking": True},
                        )
                        pre_tool_thinking.clear()
                    
                    # Emit structured status tokens
                    yield {"type": "status", "content": f"Buscando información usando {tool_name}..."}
                    
                    try:
                        start_t = _time.time()
                        result = await tool_manager.execute_tool(tool_name, **tool_args)
                        duration = f"{_time.time() - start_t:.2f}s"
                        
                        result_str = result if isinstance(result, str) else _json.dumps(result)
                        
                        await self.memory_manager.save_message(
                            conversation_id=conversation_id,
                            user_id=user_id,
                            role="tool",
                            content=result_str,
                            client_id=client_id,
                            metadata={"tool_name": tool_name, "execution_time": duration},
                        )
                        yield {"type": "status", "content": f"Búsqueda completada en {duration}. Generando respuesta..."}
                        tool_executed = True
                    except Exception as e:
                        logger.error(f"Tool execution failed: {e}")
                        await self.memory_manager.save_message(
                            conversation_id=conversation_id,
                            user_id=user_id,
                            role="tool",
                            content=f"Error executing tool {tool_name}: {e}",
                            client_id=client_id,
                            metadata={"tool_name": tool_name, "error": True},
                        )
                        yield {"type": "status", "content": f"Error al ejecutar {tool_name}: {e}"}
                        tool_executed = True
                else:
                    # If no tool call has been triggered yet, buffer as "thinking"
                    if not tool_executed:
                        pre_tool_thinking.append(token)
                    else:
                        yield token
                    
            # If model responded without any tool call, yield all buffered text normally
            if not tool_executed and pre_tool_thinking:
                for chunk in pre_tool_thinking:
                    yield chunk
                    
            if tool_executed:
                logger.info(f"Tool executed, starting RE-INFERENCE for session {session_id}")
                yield {"type": "status", "content": "Analizando resultados..."}
                
                # Reload context
                context = await self.memory_manager.get_conversation_messages(conversation_id, client_id)
                await self.inference_client.set_context(session_id, context)
                
                followup_prompt = "The tool has provided the results. Please answer the original user query using this information."
                if tool_instructions:
                    followup_prompt = f"[SYSTEM INSTRUCTIONS]\n{tool_instructions}\n[/SYSTEM INSTRUCTIONS]\n\n{followup_prompt}"
                    
                async for token in self.inference_client.infer(
                    session_id=session_id,
                    prompt=followup_prompt,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    params=None,
                    client_id=client_id,
                    model_id=effective_model,
                ):
                    if isinstance(token, dict) and token.get("type") == "tool_call":
                        logger.warning("Nested tool call attempted, ignoring.")
                    else:
                        yield token

            logger.info("Inference stream complete.")

        except ModelNotFoundError as e:
            logger.error(f"Model not found for conversation {conversation_id}: {e}")
            await self.memory_manager.mark_conversation_error(conversation_id, client_id)
            yield f" [Error: El modelo solicitado no existe en el Engine. Selecciona un modelo válido.]"

        except InferenceEngineBusyError as e:
            logger.warning(f"Engine busy for session {session_id}: {e}")
            # No marcamos la conversación en error — es un estado transitorio
            yield f" [Error: El Engine está procesando otra petición. Intenta de nuevo en un momento.]"

        except Exception as e:
            logger.error(f"Error during inference flow: {e}")
            yield f" [Error: {str(e)}]"
