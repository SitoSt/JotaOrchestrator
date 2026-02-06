import redis.asyncio as redis
from src.core.config import settings
import logging

logger = logging.getLogger(__name__)

class MemoryManager:
    def __init__(self):
        self.redis = None
        self.local_history = {} # session_id -> list
        try:
            self.redis = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
        except Exception as e:
            logger.warning(f"Redis unavailable, using in-memory storage: {e}")

    async def add_message(self, session_id: str, role: str, content: str):
        """
        Stores a message in the session history list.
        """
        message = f"{role}: {content}"
        
        if self.redis:
            try:
                key = f"session:{session_id}:history"
                await self.redis.rpush(key, message)
                await self.redis.ltrim(key, -20, -1)
                return
            except Exception as e:
                logger.error(f"Redis error: {e}. Falling back to memory.")
                self.redis = None
        
        # Fallback
        if session_id not in self.local_history:
            self.local_history[session_id] = []
        self.local_history[session_id].append(message)
        if len(self.local_history[session_id]) > 20:
             self.local_history[session_id].pop(0)

    async def get_recent_context(self, session_id: str) -> str:
        """
        Retrieves recent history as a formatted string.
        """
        if self.redis:
            try:
                key = f"session:{session_id}:history"
                messages = await self.redis.lrange(key, 0, -1)
                return "\n".join(messages) if messages else ""
            except Exception as e:
                logger.error(f"Redis error: {e}. Falling back to memory.")
                self.redis = None

        # Fallback
        return "\n".join(self.local_history.get(session_id, []))

memory_manager = MemoryManager()
