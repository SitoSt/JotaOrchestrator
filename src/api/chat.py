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
    For POST requests, we just push to controller but can't stream back easily 
    without Server-Sent Events (SSE) or Response streaming.
    User requested to "keep existing POST endpoint for compatibility".
    The original implementation pushed to event_bus.
    The new controller has 'handle_input' which is a generator.
    We need to decide if POST should wait or just fire-and-forget.
    Original was fire-and-forget (event_bus.publish).
    Let's keep it behaving similarly or consume it fully.
    """
    event = {
        "content": request.text,
        "session_id": request.session_id,
        "source": "api"
    }
    # We consume the generator but discard output for POST to maintain "compatibility" 
    # if the client doesn't expect a stream. Or we could return the full text.
    # Given "compatibility", sticking to previous behavior (async processing) is safest,
    # but we need to ensure it runs.
    # Using the helper process_event_async to drain it in background?
    # Actually, fastAPI handlers await. Let's just consume and return status.
    
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
                
            # Optional: Send a delimiter or end-of-message signal
            # The client might expect just tokens. 
            # If the user needs to know when it ends, we might implement a protocol.
            # But requirement just says "broadcast of the tokens ... in real time".
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id}")
