from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from src.core.events import event_bus

router = APIRouter()

class ChatRequest(BaseModel):
    text: str
    session_id: str = "default"

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Receives direct text input and pushes it to the event bus.
    """
    event = {
        "type": "text_input",
        "content": request.text,
        "session_id": request.session_id,
        "source": "api"
    }
    await event_bus.publish(event)
    return {"status": "received"}
