"""
quick.py
~~~~~~~~
Endpoint REST para clientes QUICK: comandos rápidos, stateless, sin streaming.
"""
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, AsyncGenerator
import logging
import json
import time

from src.core.services import inference_client, memory_manager
from src.core.tool_manager import tool_manager
from src.core.config import settings
from src.utils.tool_parser import remove_tool_calls_from_text

logger = logging.getLogger(__name__)
router = APIRouter()


# System prompt optimizado para agentes de voz con soporte de herramientas y salida TTS
QUICK_SYSTEM_PROMPT = """Eres J, un asistente de voz rápido y preciso.

REGLAS DE RESPUESTA (obligatorias):
1. Responde siempre en 1-2 frases MÁXIMO. Sin introducción, sin contexto extra.
2. PROHIBIDO usar markdown: ningún **, *, _, #, ni listas con guiones. El texto se dicta por voz.
3. Habla de forma directa y afirmativa. Omite fórmulas de cortesía innecesarias.

USO DE HERRAMIENTAS:
- Si necesitas buscar información, emite el bloque <tool_call> de forma INMEDIATA, sin ningún texto previo.
- Tras recibir el resultado de la herramienta, resume lo relevante en MÁXIMO 2 frases.
- No menciones que usaste una herramienta ni el proceso interno.

Ejemplos de respuesta correcta:
  Usuario: "Enciende la luz del salón" -> "Luz del salón encendida."
  Usuario: "Cuánto es 15 por 37" -> "Son 555."
  Usuario: "Qué tiempo hace en Madrid" -> "En Madrid hay 18 grados y cielo parcialmente nublado."
"""


class QuickRequest(BaseModel):
    """Petición para el endpoint QUICK."""
    text: str
    user_id: str = "quick_user"
    model_id: Optional[str] = None


async def _quick_stream_generator(
    client_id: int, 
    user_id: str, 
    session_id: str, 
    text: str, 
    model_id: Optional[str]
) -> AsyncGenerator[str, None]:
    """Generador que emite líneas JSON (NDJSON) con tokens de texto y metadatos."""
    
    log_prefix = f"[QUICK][Sess: {session_id}]"
    
    # Preparamos el system prompt incluyendo instrucciones de tools si aplica
    tool_instructions = tool_manager.get_system_prompt_addition(client_id=client_id)
    full_prompt = f"{QUICK_SYSTEM_PROMPT}\n"
    if tool_instructions:
        full_prompt += f"\n{tool_instructions}\n"
    
    # Parámetros optimizados para respuestas cortas (primera pasada)
    quick_params = {
        "temp": 0.3,
        "max_tokens": 150,
        "system_prompt": full_prompt
    }
    # Parámetros más estrictos para la respuesta final post-tool (forzar brevedad)
    quick_final_params = {
        "temp": 0.3,
        "max_tokens": 100,
        "system_prompt": full_prompt
    }
    
    tool_executed = False
    
    try:
        # 1. Primera pasada de inferencia
        async for token in inference_client.infer(
            session_id=session_id,
            prompt=text,
            conversation_id=f"quick_{session_id}",
            user_id=user_id,
            params=quick_params,
            client_id=client_id,
            model_id=model_id,
            persist_messages=False, # Stateless HTTP run
        ):
            if isinstance(token, dict) and token.get("type") == "tool_call":
                tc_payload = token.get("payload", {})
                tool_name = tc_payload.get("name")
                tool_args = tc_payload.get("arguments", {})
                
                logger.info(f"{log_prefix} Tool call detected: {tool_name}")
                yield json.dumps({"type": "status", "content": f"Buscando información usando {tool_name}..."}) + "\n"
                
                try:
                    start_t = time.time()
                    result = await tool_manager.execute_tool(tool_name, client_id=client_id, **tool_args)
                    duration = f"{time.time() - start_t:.2f}s"
                    result_str = result if isinstance(result, str) else json.dumps(result)
                    
                    yield json.dumps({"type": "status", "content": f"Búsqueda completada en {duration}. Generando respuesta..."}) + "\n"
                    
                    # Como QUICK es stateless, simulamos el contexto inyectando los mensajes explícitamente al engine
                    ephemeral_context = [
                        {"role": "user", "content": text},
                        {"role": "assistant", "content": f"<tool_call>{json.dumps(tc_payload)}</tool_call>"},
                        {"role": "tool", "content": result_str}
                    ]
                    await inference_client.set_context(session_id, ephemeral_context)
                    tool_executed = True
                    
                except Exception as e:
                    logger.error(f"{log_prefix} Tool {tool_name} failed: {e}")
                    yield json.dumps({"type": "status", "content": f"Error al usar {tool_name}: {e}"}) + "\n"
                    tool_executed = True
                    
            else:
                # Token de texto regular — limpiar residuos XML antes de enviar
                if not tool_executed:
                    clean_token = remove_tool_calls_from_text(token) if isinstance(token, str) else token
                    if clean_token:
                        yield json.dumps({"type": "token", "content": clean_token}) + "\n"
                    
        # 2. Segunda pasada si se ejecutó una tool (max_tokens más estricto para brevedad TTS)
        if tool_executed:
            yield json.dumps({"type": "status", "content": "Analizando resultados..."}) + "\n"
            async for token in inference_client.infer(
                session_id=session_id,
                prompt=settings.TOOL_FOLLOWUP_PROMPT,
                conversation_id=f"quick_{session_id}",
                user_id=user_id,
                params=quick_final_params,
                client_id=client_id,
                model_id=model_id,
                persist_messages=False,
            ):
                if isinstance(token, dict):
                    continue  # Ignorar tool calls anidados

                # Limpiar cualquier residuo XML antes de enviar al cliente
                clean_token = remove_tool_calls_from_text(token) if isinstance(token, str) else token
                if clean_token:
                    yield json.dumps({"type": "token", "content": clean_token}) + "\n"
                
    except Exception as e:
        logger.error(f"{log_prefix} Error in stream generator: {e}")
        yield json.dumps({"type": "error", "content": str(e)}) + "\n"
    
    finally:
        # Aseguramos cerrar la sesión efímera (cierra el websocket proxy interno del Engine)
        await inference_client.close_session(session_id)
        logger.info(f"{log_prefix} Session closed.")


@router.post("/quick")
async def quick_endpoint(
    request: QuickRequest,
    x_client_key: str = Header(..., description="Client authentication key")
):
    """
    Endpoint (NDJSON Stream) para comandos rápidos y voz (App o extensiones).
    
    Características:
    - Stateless: no guarda mensajes en DB.
    - Streaming: devuelve JSON dict por línea (NDJSON).
    - Optimizado para TTS ("Text to Speech") (Respuestas súper cortas, sin markdown).
    - Soporta de forma emulada la ejecución de herramientas.
    """
    
    # 1. Autenticación
    client_data = await memory_manager.validate_client_key(x_client_key)
    if not client_data:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # 2. Validar tipo de cliente
    client_type = client_data.get("client_type", "chat")
    if client_type != "quick":
        raise HTTPException(
            status_code=403, 
            detail=f"Client type '{client_type}' not allowed on /quick endpoint. Expected 'quick'."
        )
    
    client_id = client_data["id"]
    log_prefix = f"[QUICK][Client: {client_id}]"
    
    logger.info(f"{log_prefix} Processing QUICK request: {request.text[:50]}...")
    
    # 3. Request sesión efímera
    try:
        session_id = await inference_client.create_session()
    except Exception as e:
        logger.error(f"{log_prefix} Failed creating inferred session: {e}")
        raise HTTPException(status_code=503, detail="Inference service unavailable")
        
    # 4. Inicia proxy stream
    return StreamingResponse(
        _quick_stream_generator(
            client_id=client_id,
            user_id=request.user_id,
            session_id=session_id,
            text=request.text,
            model_id=request.model_id
        ),
        media_type="application/x-ndjson"
    )
