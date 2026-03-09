import httpx
import logging
from typing import Optional, Dict, Any, Literal
from src.core.config import settings
from src.core.constants import CONTEXT_TRUNCATED_MARKER

logger = logging.getLogger(__name__)

class MemoryManager:
    def __init__(self):
        self.base_url = settings.JOTA_DB_URL.rstrip("/")
        self.server_key = settings.JOTA_DB_SK  # Server Key para Bearer
        
        # Headers base: SIEMPRE incluyen Bearer token con el Server Key
        self.base_headers = {
            "Authorization": f"Bearer {self.server_key}",
            "Content-Type": "application/json"
        }
        
        # Connection retries for resilience
        transport = httpx.AsyncHTTPTransport(retries=3, verify=settings.SSL_VERIFY)
        self.client = httpx.AsyncClient(
            transport=transport,
            headers=self.base_headers,  # Usar headers base con Bearer
            timeout=settings.JOTA_DB_TIMEOUT,
        )

    async def close(self):
        await self.client.aclose()
        
    async def check_health(self) -> bool:
        """
        Deep health check for JotaDB connection.
        """
        try:
            # Check /health endpoint
            logger.debug(f"Verificando salud de JotaDB en {self.base_url}/health")
            response = await self.client.get(f"{self.base_url}/health")
            if response.status_code == 200:
                logger.debug("JotaDB health check: OK")
                return True
            else:
                logger.error(f"JotaDB health check falló con código: {response.status_code}")
                return False
        except httpx.ConnectError as e:
            logger.error(f"No se pudo conectar con JotaDB: {e}")
            return False
        except httpx.TimeoutException as e:
            logger.error(f"Timeout al conectar con JotaDB: {e}")
            return False
        except Exception as e:
            logger.error(f"Error inesperado en health check de JotaDB: {e}")
            return False

    async def verify_connection(self) -> bool:
        """
        Verifica la conexión completa con JotaDB incluyendo autenticación.
        Llama a /auth/internal/ con ORCHESTRATOR_ID y ORCHESTRATOR_KEY.
        """
        try:
            # Primero verificar health
            if not await self.check_health():
                return False
            
            # Autenticación interna con el orchestrator
            logger.debug("Probando autenticación interna con JotaDB...")
            
            # Headers para autenticación interna: Bearer + X-Service-ID + X-API-Key
            internal_auth_headers = {
                **self.base_headers,  # Incluye Bearer token (JOTA_DB_SK)
                "X-Service-ID": settings.ORCHESTRATOR_ID,
                "X-API-Key": settings.ORCHESTRATOR_API_KEY
            }
            
            response = await self.client.get(
                f"{self.base_url}/auth/internal",
                headers=internal_auth_headers,
            )
            
            # Si obtenemos 200, la autenticación funcionó
            if response.status_code == 200:
                logger.debug("✅ Autenticación interna con JotaDB verificada correctamente")
                return True
            elif response.status_code in [401, 403]:
                logger.error(f"❌ Autenticación interna con JotaDB falló: código {response.status_code}")
                logger.error(f"   Verifica las credenciales ORCHESTRATOR_ID y ORCHESTRATOR_API_KEY")
                return False
            else:
                logger.warning(f"⚠️  Respuesta inesperada de JotaDB: {response.status_code}")
                return False
                
        except httpx.ConnectError as e:
            logger.error(f"❌ No se pudo conectar con JotaDB: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Error al verificar conexión con JotaDB: {e}")
            return False

    async def validate_client_key(self, client_key: str) -> Optional[Dict[str, Any]]:
        """
        Validates the client key against JotaDB.
        Returns the Client information (including integer id) if valid, or None.
        Para /auth/client: Solo envía Bearer token + X-API-Key
        """
        try:
            # Headers para autenticación de cliente: Bearer + X-API-Key solamente
            client_headers = {
                **self.base_headers,  # Incluye Bearer token
                "X-API-Key": client_key
            }
            
            response = await self.client.get(
                f"{self.base_url}/auth/client",
                headers=client_headers
            )
            
            if response.status_code == 200:
                return response.json()
            logger.warning(f"Client key validation failed: {response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Error validating client key: {e}")
            return False

    async def create_conversation(self, user_id: str, client_id: int, model_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates a new conversation in JotaDB.
        Optionally links it to a specific model via model_id.
        Returns the conversation object (dict).
        """
        try:
            service_headers = {
                **self.base_headers,
                "X-API-Key": settings.ORCHESTRATOR_API_KEY,
                "X-Client-ID": str(client_id)
            }

            payload: Dict[str, Any] = {"client_id": user_id, "status": "active"}
            if model_id:
                payload["model_id"] = model_id

            create_response = await self.client.post(
                f"{self.base_url}/chat/conversations",
                json=payload,
                headers=service_headers,
            )
            create_response.raise_for_status()
            return create_response.json()

        except Exception as e:
            logger.error(f"Error managing conversation for user {user_id}: {e}")
            raise e

    async def get_conversation(self, conversation_id: str, client_id: Any) -> Optional[Dict[str, Any]]:
        """
        Retrieves a single conversation object from JotaDB.
        Returns the dict (including model_id if set) or None on failure.
        """
        try:
            service_headers = {
                **self.base_headers,
                "X-API-Key": settings.ORCHESTRATOR_API_KEY,
                "X-Client-ID": str(client_id),
            }
            response = await self.client.get(
                f"{self.base_url}/chat/conversations/{conversation_id}",
                headers=service_headers,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get conversation {conversation_id}: {e}")
            return None

    async def set_conversation_model(self, conversation_id: str, client_id: Any, model_id: str) -> bool:
        """
        Updates the model_id linked to a conversation via PATCH.
        Returns True on success, False on failure.
        """
        try:
            service_headers = {
                **self.base_headers,
                "X-API-Key": settings.ORCHESTRATOR_API_KEY,
                "X-Client-ID": str(client_id),
            }
            response = await self.client.patch(
                f"{self.base_url}/chat/conversations/{conversation_id}",
                json={"model_id": model_id},
                headers=service_headers,
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to set model for conversation {conversation_id}: {e}")
            return False

    async def get_conversation_messages(self, conversation_id: str, client_id: Any, limit: int = 50) -> list:
        """
        Retrieves message history from JotaDB for context recovery.
        Returns a list of {"role": ..., "content": ...} dicts.
        Optimizes tool role outputs by fetching extra context and truncating long tool data.
        """
        try:
            url = f"{self.base_url}/chat/{conversation_id}/messages"
            # Using orchestrator credentials since it's an internal call 
            service_headers = {
                 **self.base_headers,
                 "X-API-Key": settings.ORCHESTRATOR_API_KEY,
                 "X-Client-ID": str(client_id)
            }
            
            # Fetch extra history to account for tool invocations
            fetch_limit = max(limit * 2, 100)
            response = await self.client.get(url, params={"limit": fetch_limit}, headers=service_headers)
            response.raise_for_status()
            
            raw_messages = response.json()
            processed_messages = []
            
            for msg in raw_messages:
                # Local optimization for tool calls to avoid context inflation
                if msg.get("role") == "tool":
                    content = msg.get("content", "")
                    # Cap tool output footprint to ~1500 chars to avoid model distraction and token explosion
                    if content and len(content) > settings.MEMORY_TOOL_OUTPUT_CAP:
                        msg["content"] = content[:settings.MEMORY_TOOL_OUTPUT_CAP] + CONTEXT_TRUNCATED_MARKER
                processed_messages.append(msg)
                
            # Return up to 'fetch_limit' elements; the downstream model needs the tool traces chronologically
            return processed_messages
        except Exception as e:
            logger.error(f"Failed to get messages for conversation {conversation_id}: {e}")
            return []

    async def get_user_conversations(self, client_id: Any, limit: int = 10) -> list:
        """
        Retrieves the last N conversations for a user from JotaDB.
        Returns a list of conversation objects, most recent first.
        """
        try:
            # Using orchestrator credentials
            service_headers = {
                 **self.base_headers,
                 "X-API-Key": settings.ORCHESTRATOR_API_KEY,
                 "X-Client-ID": str(client_id)
            }
            response = await self.client.get(
                f"{self.base_url}/chat/conversations",
                params={"limit": limit},
                headers=service_headers
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get conversations for user {user_id}: {e}")
            return []

    async def save_message(
        self,
        conversation_id: str,
        user_id: str,
        role: Literal["user", "assistant", "system", "tool"],
        content: str,
        client_id: Any,
        metadata: Optional[Dict] = None,
    ):
        """
        Saves a message to JotaDB.

        Args:
            metadata: Datos adicionales a persistir con el mensaje, por ejemplo
                      {"model_id": "llama3-8b"} para trazabilidad del modelo generador.
                      O para tools: {"tool_name": "tavily", "execution_time": "1.2s"}
        """
        if role not in ["user", "assistant", "system", "tool"]:
            logger.error(f"Invalid message role: {role} - Message not saved.")
            return

        try:
            payload: Dict[str, Any] = {"role": role, "content": content}
            if metadata:
                payload["metadata"] = metadata

            service_headers = {
                **self.base_headers,
                "X-API-Key": settings.ORCHESTRATOR_API_KEY,
                "X-Client-ID": str(client_id)
            }

            url = f"{self.base_url}/chat/{conversation_id}/messages"
            response = await self.client.post(url, json=payload, headers=service_headers)

            if response.status_code == 422:
                logger.error(f"422 Error on POST /chat/{conversation_id}/messages: {response.text}")
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to save message to JotaDB: {e}")


    async def mark_conversation_error(self, conversation_id: str, client_id: Any):
         """
         Sets conversation status to error.
         """
         try:
            url = f"{self.base_url}/chat/conversations/{conversation_id}"
            payload = {"status": "error"}
            # Using orchestrator credentials
            service_headers = {
                 **self.base_headers,
                 "X-API-Key": settings.ORCHESTRATOR_API_KEY,
                 "X-Client-ID": str(client_id)
            }
            await self.client.patch(url, json=payload, headers=service_headers)
         except Exception as e:
             logger.error(f"Failed to mark conversation error: {e}")
