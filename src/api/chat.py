from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from src.core.controller import jota_controller
from src.core.memory import memory_manager
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

class ChatRequest(BaseModel):
    text: str
    user_id: str = "api_user"
    client_key: str = None

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Receives direct text input.
    Kept for compatibility with REST clients.
    """
    # 1. Authentication
    if not request.client_key or not await memory_manager.validate_client_key(request.client_key):
        return {"status": "error", "message": "Unauthorized"}

    try:
        # 2. Conversation & Session Management
        conversation = await memory_manager.get_or_create_conversation(request.user_id)
        conversation_id = conversation["id"]
        session_id = conversation.get("inference_session_id")
        
        if not session_id:
            from src.services.inference import inference_client
            session_id = await inference_client.get_session(request.user_id)
            await memory_manager.update_conversation_session(conversation_id, session_id)

        # 3. Save User Message
        await memory_manager.save_message(conversation_id, "user", request.text)

        event = {
            "content": request.text,
            "session_id": session_id,
            "conversation_id": conversation_id,
            "source": "api"
        }
        
        full_response = ""
        async for token in jota_controller.handle_input(event):
            full_response += token
            
        return {"status": "success", "response": full_response}

    except Exception as e:
        logger.error(f"Error in REST chat: {e}")
        return {"status": "error", "message": str(e)}

@router.websocket("/ws/chat/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    # 1. Authentication
    client_key = websocket.query_params.get("client_key")
    if not client_key or not await memory_manager.validate_client_key(client_key):
        logger.warning(f"Unauthorized access attempt for user {user_id}")
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    logger.info(f"WebSocket connected for user {user_id}")
    
    try:
        # 2. Conversation & Session Management
        conversation = await memory_manager.get_or_create_conversation(user_id)
        conversation_id = conversation["id"]
        session_id = conversation.get("inference_session_id")
        
        if not session_id:
            logger.info(f"No active inference session for conversation {conversation_id}. Creating new one...")
            from src.services.inference import inference_client
            session_id = await inference_client.get_session(user_id)
            await memory_manager.update_conversation_session(conversation_id, session_id)
        
        logger.info(f"Using conversation {conversation_id} and session {session_id}")

        while True:
            data = await websocket.receive_text()
            logger.info(f"Received via WS from {user_id}: {data}")
            
            # 3. Save User Message
            await memory_manager.save_message(conversation_id, "user", data)
            
            payload = {
                "content": data,
                "session_id": session_id,
                "conversation_id": conversation_id,
                "source": "websocket"
            }
            
            # 4. Stream tokens back
            async for token in jota_controller.handle_input(payload):
                await websocket.send_text(token)
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        await websocket.close(code=1011)
