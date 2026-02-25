from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Header
from pydantic import BaseModel
from src.core.services import jota_controller, memory_manager, inference_client
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

class ChatRequest(BaseModel):
    text: str
    user_id: str = "api_user"
    # client_key removed from body, now in header X-API-Key

@router.post("/chat")
async def chat_endpoint(request: ChatRequest, x_api_key: str = Header(None, alias="X-API-Key")):
    """
    Receives direct text input.
    Kept for compatibility with REST clients.
    """
    # 1. Authentication
    if not x_api_key:
        return {"status": "error", "message": "Missing X-API-Key header"}
    
    client_data = await memory_manager.validate_client_key(x_api_key)
    if not client_data:
        return {"status": "error", "message": "Unauthorized"}
    client_id = client_data["id"]

    try:
        # 2. Conversation & Session Management
        conversation = await memory_manager.get_or_create_conversation(client_id)
        conversation_id = conversation["id"]
        session_id = conversation.get("inference_session_id")
        
        if not session_id:
            # Explicitly create a new session
            session_id = await inference_client.create_session()
            await memory_manager.update_conversation_session(conversation_id, session_id, client_id)

        # Contextual Log
        log_prefix = f"[Conv: {conversation_id}][Sess: {session_id}]"
        logger.info(f"{log_prefix} Processing REST chat request")

        # 3. Save User Message
        await memory_manager.save_message(conversation_id, "user", request.text, client_id)

        event = {
            "content": request.text,
            "session_id": session_id,
            "conversation_id": conversation_id,
            "client_id": client_id,
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
    client_key = websocket.headers.get("X-API-Key")
    
    if not client_key:
        logger.warning(f"Missing X-API-Key header for user {user_id}")
        await websocket.close(code=4001, reason="Missing X-API-Key")
        return
    
    client_data = await memory_manager.validate_client_key(client_key)
    if not client_data:
        logger.warning(f"Unauthorized access attempt for user {user_id}")
        await websocket.close(code=4001, reason="Unauthorized")
        return
    client_id = client_data["id"]

    await websocket.accept()
    logger.info(f"WebSocket connected for user {user_id}")
    
    session_id = None # Keep track for aborting
    
    try:
        # 2. Conversation & Session Management
        conversation = await memory_manager.get_or_create_conversation(client_id)
        conversation_id = conversation["id"]
        session_id = conversation.get("inference_session_id")
        
        if not session_id:
            logger.info(f"No active inference session for conversation {conversation_id}. Creating new one...")
            session_id = await inference_client.create_session()
            await memory_manager.update_conversation_session(conversation_id, session_id, client_id)
        
        log_prefix = f"[Conv: {conversation_id}][Sess: {session_id}]"
        logger.info(f"{log_prefix} Session ready. Waiting for messages...")

        while True:
            data = await websocket.receive_text()
            logger.info(f"{log_prefix} Received via WS: {data}")
            
            # 3. Save User Message
            await memory_manager.save_message(conversation_id, "user", data, client_id)
            
            payload = {
                "content": data,
                "session_id": session_id,
                "conversation_id": conversation_id,
                "client_id": client_id,
                "source": "websocket"
            }
            
            # 4. Stream tokens back
            async for token in jota_controller.handle_input(payload):
                await websocket.send_text(token)
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id}")
        if session_id:
            logger.info(f"Aborting session {session_id} due to client disconnect")
            await inference_client.abort_session(session_id)
            
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        await websocket.close(code=1011)
