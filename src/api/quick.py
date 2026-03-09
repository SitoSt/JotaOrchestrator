"""
quick.py
~~~~~~~~
Endpoint REST para clientes QUICK: comandos rápidos, stateless, sin streaming.
"""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

from src.core.services import inference_client, memory_manager
from src.core.tool_manager import tool_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# System prompt optimizado para respuestas cortas y directas
QUICK_SYSTEM_PROMPT = """Eres J, un asistente virtual eficiente.
REGLAS ESTRICTAS:
- Responde en 1-3 frases máximo
- Sin explicaciones innecesarias
- Directo al grano
- Para comandos, confirma con una palabra o frase corta
- Para búsquedas, resume los puntos clave brevemente

Ejemplos:
- "Enciende la luz del salón" → "Luz del salón encendida."
- "¿Qué tiempo hace en Madrid?" → "Madrid: 18°C, parcialmente nublado."
- "Pon un timer de 5 minutos" → "Timer de 5 minutos iniciado."
"""


class QuickRequest(BaseModel):
    """Petición para el endpoint QUICK."""
    text: str
    user_id: str = "quick_user"


class QuickResponse(BaseModel):
    """Respuesta del endpoint QUICK."""
    status: str
    response: str
    execution_time_ms: Optional[float] = None


@router.post("/quick", response_model=QuickResponse)
async def quick_endpoint(
    request: QuickRequest,
    x_client_key: str = Header(..., description="Client authentication key")
):
    """
    Endpoint para comandos rápidos y respuestas cortas.
    
    Características:
    - Stateless: no guarda contexto ni mensajes
    - Sin streaming: devuelve respuesta completa
    - Optimizado para respuestas cortas (max_tokens reducido)
    - System prompt específico para brevedad
    """
    import time
    start_time = time.time()
    
    # 1. Autenticación
    client_data = await memory_manager.validate_client_key(x_client_key)
    if not client_data:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # 2. Verificar que el cliente es de tipo QUICK
    client_type = client_data.get("client_type", "chat")  # default a chat por compatibilidad
    if client_type != "quick":
        raise HTTPException(
            status_code=403, 
            detail=f"Client type '{client_type}' not allowed on /quick endpoint. Expected 'quick'."
        )
    
    client_id = client_data["id"]
    log_prefix = f"[QUICK][Client: {client_id}]"
    
    try:
        logger.info(f"{log_prefix} Processing: {request.text[:50]}...")
        
        # 3. Crear sesión efímera (sin tracking por user_id)
        session_id = await inference_client.create_session()
        
        # 4. Preparar prompt con system prompt QUICK
        tool_instructions = tool_manager.get_system_prompt_addition()
        
        full_prompt = f"{QUICK_SYSTEM_PROMPT}\n"
        if tool_instructions:
            full_prompt += f"\n{tool_instructions}\n"
        full_prompt += f"\nUsuario: {request.text}"
        
        # 5. Parámetros optimizados para respuestas cortas
        quick_params = {
            "temp": 0.3,        # Menos creatividad, más determinismo
            "max_tokens": 150,  # Límite de tokens reducido
        }
        
        # 6. Inferencia (acumulamos tokens sin streaming al cliente)
        full_response = ""
        async for token in inference_client.infer(
            session_id=session_id,
            prompt=full_prompt,
            conversation_id=f"quick_{session_id}",  # ID temporal
            user_id=request.user_id,
            params=quick_params,
            client_id=client_id,
            model_id=None,  # Usa el modelo cargado actualmente
            persist_messages=False,  # NO persistir mensajes QUICK
        ):
            if isinstance(token, dict):
                # Tool calls - por ahora los procesamos inline
                if token.get("type") == "tool_call":
                    # TODO: Implementar tool execution para QUICK
                    logger.info(f"{log_prefix} Tool call detected (not yet implemented)")
                continue
            full_response += token
        
        # 7. Cerrar sesión inmediatamente (stateless)
        await inference_client.close_session(session_id)
        
        execution_time = (time.time() - start_time) * 1000
        logger.info(f"{log_prefix} Completed in {execution_time:.0f}ms")
        
        return QuickResponse(
            status="success",
            response=full_response.strip(),
            execution_time_ms=round(execution_time, 2)
        )
        
    except Exception as e:
        logger.error(f"{log_prefix} Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
