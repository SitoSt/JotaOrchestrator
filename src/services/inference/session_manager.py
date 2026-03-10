"""
Inference Session Lifecycle Management.

Provides `InferenceSessionMixin`, which manages the creation, tracking, and 
cleanup of user-specific inference sessions on the InferenceCenter side.
"""
import asyncio
import json
import logging
from typing import Dict, Any, Optional

from src.core.config import settings

logger = logging.getLogger(__name__)

class InferenceSessionMixin:
    """
    Mixin para manejar el ciclo de vida de las sesiones de inferencia por usuario.
    """

    async def create_session(self) -> str:
        """
        Requests a new session ID from the engine.
        """
        if not self.is_connected:
            raise Exception("Inference Engine not connected")

        async with self.lock:
             self._session_creation_future = asyncio.Future()
             try:
                 await self.websocket.send(json.dumps({"op": "create_session"}))
                 return await asyncio.wait_for(self._session_creation_future, timeout=settings.INFERENCE_SESSION_TIMEOUT)
             finally:
                 self._session_creation_future = None

    async def abort_session(self, session_id: str):
        """
        Sends abort signal for a specific session.
        """
        if self.is_connected:
             try:
                 await self.websocket.send(json.dumps({
                     "op": "abort",
                     "session_id": session_id
                 }))
                 logger.info(f"Aborted session {session_id}")
             except Exception as e:
                 logger.error(f"Failed to abort session {session_id}: {e}")

    async def close_session(self, session_id: str):
        """
        Closes and frees the session from the InferenceCenter.
        """
        if self.is_connected:
             try:
                 await self.websocket.send(json.dumps({
                     "op": "close_session",
                     "session_id": session_id
                 }))
                 logger.info(f"Closed session {session_id}")
             except Exception as e:
                 logger.error(f"Failed to close session {session_id}: {e}")

    async def ensure_session(self, user_id: str) -> str:
        """
        Creates a fresh session for a user, closing any existing one first.
        Tracks active sessions to avoid leaving dangling resources.
        """
        old_session = self._user_sessions.get(user_id)
        if old_session:
            logger.info(f"Closing previous session {old_session} for user {user_id}")
            await self.close_session(old_session)
        
        session_id = await self.create_session()
        self._user_sessions[user_id] = session_id
        logger.info(f"New session {session_id} assigned to user {user_id}")
        return session_id

    async def set_context(self, session_id: str, messages: list):
        """
        Sends conversation history to the InferenceCenter for context recovery.
        Must be called after create_session and before infer.
        """
        if not self.is_connected:
            raise Exception("Inference Engine not connected")
        
        payload = {
            "op": "set_context",
            "session_id": session_id,
            "context": {
                "messages": messages
            }
        }
        await self.websocket.send(json.dumps(payload))
        logger.info(f"Context set for session {session_id} ({len(messages)} messages)")

    async def release_session(self, user_id: str):
        """
        Closes and unregisters a user's active session.
        Called on client disconnect to free InferenceCenter resources.
        """
        session_id = self._user_sessions.pop(user_id, None)
        if session_id:
            logger.info(f"Releasing session {session_id} for user {user_id}")
            await self.close_session(session_id)
