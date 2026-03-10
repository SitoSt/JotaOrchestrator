"""
Input handling logic for the Orchestrator Controller.

Provides the `JotaInputMixin` which defines the main inference flow, coordinating
model verification, token streaming, tool execution, and error handling.
"""
import logging
from typing import AsyncGenerator, TYPE_CHECKING
from src.services.inference import InferenceEngineBusyError, ModelNotFoundError

if TYPE_CHECKING:
    from src.core.memory import MemoryManager
    from src.services.inference import InferenceClient

logger = logging.getLogger(__name__)

class JotaInputMixin:
    """
    Mixin para manejar el flujo principal de inferencia y tools.
    """

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
        stateless = payload.get("stateless", False)
        system_prompt_override = payload.get("system_prompt_override")

        if not session_id or not conversation_id or not user_id:
            logger.error("Missing session_id, conversation_id, or user_id in payload")
            yield " [Error: Internal Context Missing]"
            return

        logger.info(f"Controller processing input for session {session_id}")

        try:
            # Pre-infer: garantizar que el modelo correcto está cargado
            if not stateless:
                await self._ensure_model_loaded(conversation_id, client_id)

            # Usar el modelo activo real (puede haber sido actualizado por _ensure_model_loaded)
            effective_model = self.inference_client.current_engine_model or model_id

            from src.core.tool_manager import tool_manager, ToolPermissionError
            from src.core.config import settings as _settings
            from src.utils.tool_parser import extract_tool_calls, remove_tool_calls_from_text
            import time as _time
            import json as _json
            tool_instructions = tool_manager.get_system_prompt_addition(client_id=client_id)

            base_prompt = system_prompt_override or _settings.AGENT_BASE_SYSTEM_PROMPT
            system_prompt = base_prompt
            if tool_instructions:
                logger.info(f"[TRACE] Tool instructions active ({len(tool_instructions)} chars)")
                system_prompt += "\\n\\n" + tool_instructions
            else:
                logger.warning("[TRACE] ⚠️  No tools registered — model cannot access external data")

            logger.debug(
                f"[TRACE] System prompt built — tools={bool(tool_instructions)} total_chars={len(system_prompt)}"
            )

            infer_params = {"system_prompt": system_prompt}

            logger.info(
                f"[TRACE][Conv: {conversation_id}] Calling infer — "
                f"effective_model={effective_model!r} "
                f"engine_current={self.inference_client.current_engine_model!r}"
            )
            
            tool_executed = False
            pre_tool_thinking = []   # Buffer for text emitted BEFORE the tool call
            
            async for token in self.inference_client.infer(
                session_id=session_id,
                prompt=content,
                conversation_id=conversation_id,
                user_id=user_id,
                params=infer_params,
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
                        if not stateless:
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
                        result = await tool_manager.execute_tool(tool_name, client_id=client_id, **tool_args)
                        duration = f"{_time.time() - start_t:.2f}s"
                        
                        result_str = result if isinstance(result, str) else _json.dumps(result)

                        if not stateless:
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
                        if not stateless:
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
                    if not tool_executed:
                        pre_tool_thinking.append(token)

                        # Text-based detection: fallback when inference.py streaming
                        # parser misses the tag boundaries between chunks.
                        accumulated = "".join(pre_tool_thinking)
                        detected_calls = extract_tool_calls(accumulated)

                        if detected_calls:
                            tool_call_data = detected_calls[0]
                            tool_name = tool_call_data["name"]
                            tool_args = tool_call_data["arguments"]

                            clean_thinking = remove_tool_calls_from_text(accumulated)
                            if clean_thinking.strip() and not stateless:
                                await self.memory_manager.save_message(
                                    conversation_id=conversation_id,
                                    user_id=user_id,
                                    role="assistant",
                                    content=clean_thinking,
                                    client_id=client_id,
                                    metadata={"model_id": effective_model, "thinking": True},
                                )
                            pre_tool_thinking.clear()

                            logger.info(f"[TOOL] Detected from text stream: {tool_name} args={tool_args}")
                            yield {"type": "status", "content": f"Buscando información usando {tool_name}..."}

                            try:
                                start_t = _time.time()
                                result = await tool_manager.execute_tool(tool_name, client_id=client_id, **tool_args)
                                duration = f"{_time.time() - start_t:.2f}s"
                                result_str = result if isinstance(result, str) else _json.dumps(result)
                                if not stateless:
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
                                logger.error(f"Tool execution failed (text detection): {e}")
                                if not stateless:
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
                        yield token
                    
            # If model responded without any tool call, yield all buffered text normally
            if not tool_executed and pre_tool_thinking:
                for chunk in pre_tool_thinking:
                    yield chunk
                    
            if tool_executed:
                logger.info(f"Tool executed, starting RE-INFERENCE for session {session_id}")
                yield {"type": "status", "content": "Analizando resultados..."}
                
                # Reload context (skip for stateless — no history to reload)
                if not stateless:
                    context = await self.memory_manager.get_conversation_messages(conversation_id, client_id)
                    await self.inference_client.set_context(session_id, context)
                
                followup_prompt = _settings.TOOL_FOLLOWUP_PROMPT
                    
                async for token in self.inference_client.infer(
                    session_id=session_id,
                    prompt=followup_prompt,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    params=infer_params,
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
