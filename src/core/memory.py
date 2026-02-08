import httpx
import logging
from typing import Optional, Dict, Any, Literal
from src.core.config import settings

logger = logging.getLogger(__name__)

class MemoryManager:
    def __init__(self):
        self.base_url = settings.JOTA_DB_URL.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {settings.JOTA_DB_API_KEY}",
            "Content-Type": "application/json"
        }
        # Connection retries for resilience
        transport = httpx.AsyncHTTPTransport(retries=3)
        self.client = httpx.AsyncClient(transport=transport, headers=self.headers, timeout=10.0)

    async def close(self):
        await self.client.aclose()
        
    async def check_health(self) -> bool:
        """
        Deep health check for JotaDB connection.
        """
        try:
            # Assuming JotaDB has a health endpoint or we can check via a lightweight call
            # using auth/client with a dummy key or similar if no dedicated health endpoint exists.
            # Ideally JotaDB should have /health. Let's assume it does or we check connectivity.
            response = await self.client.get(f"{self.base_url}/health") # Adjust endpoint if needed
            return response.status_code == 200
        except Exception as e:
            logger.error(f"MemoryManager Health Check Failed: {e}")
            return False

    async def validate_client_key(self, client_key: str) -> bool:
        """
        Validates the client key against JotaDB.
        """
        try:
            response = await self.client.get(f"{self.base_url}/auth/client", params={"client_key": client_key})
            if response.status_code == 200:
                return True
            logger.warning(f"Client key validation failed: {response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Error validating client key: {e}")
            return False

    async def get_or_create_conversation(self, user_id: str) -> Dict[str, Any]:
        """
        Retrieves active conversation for user_id or creates a new one.
        Returns the conversation object (dict).
        """
        try:
            # 1. Try to find active conversation
            response = await self.client.get(f"{self.base_url}/chat/conversation", params={"user_id": user_id, "status": "active"})
            if response.status_code == 200:
                conversations = response.json()
                if conversations and isinstance(conversations, list) and len(conversations) > 0:
                    return conversations[0]

            # 2. Create new conversation if none found
            payload = {"user_id": user_id, "status": "active"}
            create_response = await self.client.post(f"{self.base_url}/chat/conversation", json=payload)
            create_response.raise_for_status()
            return create_response.json()

        except Exception as e:
            logger.error(f"Error managing conversation for user {user_id}: {e}")
            raise e

    async def update_conversation_session(self, conversation_id: str, session_id: str):
        """
        Links the JotaDB conversation with the Inference Engine session ID.
        """
        try:
            url = f"{self.base_url}/chat/conversation/{conversation_id}/session"
            payload = {"inference_session_id": session_id}
            response = await self.client.patch(url, json=payload)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to update session ID for conversation {conversation_id}: {e}")
            # Non-critical? Maybe critical if we lose the link.
            pass

    async def save_message(self, conversation_id: str, role: Literal["user", "assistant", "system"], content: str):
        """
        Saves a message to JotaDB.
        """
        if role not in ["user", "assistant", "system"]:
            logger.error(f"Invalid message role: {role}")
            return

        try:
            payload = {
                "conversation_id": conversation_id,
                "role": role,
                "content": content
            }
            response = await self.client.post(f"{self.base_url}/chat/message", json=payload)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to save message to JotaDB: {e}")

    async def mark_conversation_error(self, conversation_id: str):
         """
         Sets conversation status to error.
         """
         try:
            url = f"{self.base_url}/chat/conversation/{conversation_id}"
            payload = {"status": "error"}
            await self.client.patch(url, json=payload)
         except Exception as e:
             logger.error(f"Failed to mark conversation error: {e}")
