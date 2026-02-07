from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from src.core.controller import jota_controller
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

class ChatRequest(BaseModel):
    text: str
    session_id: str = "default"

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Receives direct text input.
    Kept for compatibility with REST clients.
    """
    event = {
        "content": request.text,
        "session_id": request.session_id,
        "source": "api"
    }
    # Consume the generator fully to process the request, but return the aggregated response (or status)
    # as this is a standard POST request, not a stream.
    
    full_response = ""
    async for token in jota_controller.handle_input(event):
        full_response += token
        
    return {"status": "success", "response": full_response}

@router.websocket("/ws/chat/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    logger.info(f"WebSocket connected for user {user_id}")
    
    try:
        while True:
            data = await websocket.receive_text()
            logger.info(f"Received via WS from {user_id}: {data}")
            
            payload = {
                "content": data,
                "session_id": user_id, # Using user_id as session_id context
                "source": "websocket"
            }
            
            # Stream tokens back
            async for token in jota_controller.handle_input(payload):
                await websocket.send_text(token)
                
            # Stream tokens back in real-time
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id}")
