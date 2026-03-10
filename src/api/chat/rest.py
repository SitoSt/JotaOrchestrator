"""
REST API endpoints for chat operations.

This module provides standard HTTP REST endpoints for client applications
to list available models, manage conversation state, and send text prompts.
"""
from fastapi import APIRouter, Query, Header, HTTPException
from pydantic import BaseModel
from typing import Optional
from src.core.services import jota_controller, memory_manager, inference_client
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/chat/models")
async def get_available_models(
    x_client_key: str = Header(..., description="Client authentication key"),
):
    """
    Retorna la lista de modelos disponibles en el InferenceCenter.
    La respuesta se cachea durante 5 minutos en el InferenceClient para
    evitar sobrecargar el bus de mensajes entre servicios.
    """
    client_data = await memory_manager.validate_client_key(x_client_key)
    if not client_data:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        models = await inference_client.list_models()
        return {"status": "success", "models": models}
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=503, detail=f"Engine unavailable: {e}")


class ConversationModelUpdate(BaseModel):
    model_id: str


@router.patch("/chat/conversations/{conversation_id}")
async def update_conversation_model(
    conversation_id: str,
    body: ConversationModelUpdate,
    x_client_key: str = Header(..., description="Client authentication key"),
):
    """
    Actualiza el modelo asignado a una conversación.

    Valida que el model_id exista en la lista del Engine antes de persistir,
    garantizando que no se asigne un modelo inexistente.
    """
    client_data = await memory_manager.validate_client_key(x_client_key)
    if not client_data:
        raise HTTPException(status_code=401, detail="Unauthorized")
    client_id = client_data["id"]

    # Validar que el modelo existe en el Engine (usa caché TTL)
    try:
        available_models = await inference_client.list_models()
        model_ids = (
            [m.get("id") or m.get("model_id") or m for m in available_models]
            if isinstance(available_models, list)
            else []
        )
        if model_ids and body.model_id not in model_ids:
            raise HTTPException(
                status_code=404,
                detail=f"Model '{body.model_id}' not found in Engine. Available: {model_ids}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Could not validate model existence (Engine may be unavailable): {e}")
        # Si el Engine no responde, permitimos el update DB de todos modos

    ok = await memory_manager.set_conversation_model(conversation_id, client_id, body.model_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update conversation model in DB")

    return {"status": "success", "conversation_id": conversation_id, "model_id": body.model_id}


@router.get("/chat/conversations/{user_id}")
async def get_conversations(
    user_id: str,
    x_client_key: str = Header(..., description="Client authentication key"),
    limit: int = Query(10, ge=1, le=100, description="Number of conversations to retrieve")
):
    """
    Returns the last N conversations for a given user.
    """
    client_data = await memory_manager.validate_client_key(x_client_key)
    if not x_client_key or not client_data:
        return {"status": "error", "message": "Unauthorized"}
    client_id = client_data["id"]

    try:
        conversations = await memory_manager.get_user_conversations(client_id, limit=limit)
        return {"status": "success", "conversations": conversations}
    except Exception as e:
        logger.error(f"Error retrieving conversations for {user_id}: {e}")
        return {"status": "error", "message": str(e)}

@router.get("/chat/conversations/{user_id}/{conversation_id}/messages")
async def get_conversation_messages(
    user_id: str,
    conversation_id: str,
    x_client_key: str = Header(..., description="Client authentication key"),
    limit: int = Query(50, ge=1, le=1000, description="Number of messages to retrieve")
):
    """
    Returns the messages for a specific conversation.
    """
    client_data = await memory_manager.validate_client_key(x_client_key)
    if not x_client_key or not client_data:
        return {"status": "error", "message": "Unauthorized"}
    client_id = client_data["id"]

    try:
        messages = await memory_manager.get_conversation_messages(conversation_id, client_id, limit=limit)
        return {"status": "success", "messages": messages}
    except Exception as e:
        logger.error(f"Error retrieving messages for conversation {conversation_id}: {e}")
        return {"status": "error", "message": str(e)}

class ChatRequest(BaseModel):
    """
    Schema for a generic chat request payload.
    
    Attributes:
        text (str): The user's input message.
        user_id (str): The identifier for the user initiating the request.
        model_id (str): Optional; the specific inference model to handle the message.
    """
    text: str
    user_id: str = "api_user"
    model_id: str = None  # Optional: model to use for this conversation

@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    x_client_key: str = Header(..., description="Client authentication key")
):
    """
    Receives direct text input.
    Kept for compatibility with REST clients.
    """
    # 1. Authentication
    client_data = await memory_manager.validate_client_key(x_client_key)
    if not x_client_key or not client_data:
        return {"status": "error", "message": "Unauthorized"}
        
    # 2. Validar tipo de cliente
    client_type = client_data.get("client_type", "chat")
    if client_type == "quick":
        return {
            "status": "error", 
            "message": "Client type 'quick' not allowed on /chat endpoint. Use /quick instead."
        }
        
    client_id = client_data["id"]

    try:
        # 3. Conversation Management
        conversation = await memory_manager.create_conversation(
            request.user_id, client_id=client_id, model_id=request.model_id
        )
        conversation_id = conversation["id"]

        # 3. Ephemeral Session (aborts previous if exists)
        session_id = await inference_client.ensure_session(request.user_id)

        log_prefix = f"[Conv: {conversation_id}][Sess: {session_id}]"
        logger.info(f"{log_prefix} Processing REST chat request")

        # 4. Recover context from DB and inject into session
        context = await memory_manager.get_conversation_messages(conversation_id, client_id)
        await inference_client.set_context(session_id, context)

        # 5. Save User Message
        await memory_manager.save_message(
            conversation_id=conversation_id, 
            user_id=request.user_id,
            role="user", 
            content=request.text,
            client_id=client_id
        )

        event = {
            "content": request.text,
            "session_id": session_id,
            "conversation_id": conversation_id,
            "user_id": request.user_id,
            "client_id": client_id,
            "model_id": request.model_id,
            "source": "api"
        }
        
        full_response = ""
        async for token in jota_controller.handle_input(event):
            if isinstance(token, dict):
                # Status messages are not relevant for REST responses
                continue
            full_response += token
            
        return {"status": "success", "response": full_response}

    except Exception as e:
        logger.error(f"Error in REST chat: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        # Release session resources
        await inference_client.release_session(request.user_id)
