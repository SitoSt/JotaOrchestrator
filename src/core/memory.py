import httpx
import logging
from typing import Optional, Dict, Any, Literal
from src.core.config import settings

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
        transport = httpx.AsyncHTTPTransport(retries=3)
        self.client = httpx.AsyncClient(
            transport=transport, 
            headers=self.base_headers,  # Usar headers base con Bearer
            timeout=10.0,
            verify=settings.SSL_VERIFY  # SSL certificate verification
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
            
            # Headers para autenticación interna: Bearer + X-Client-ID + X-API-Key
            internal_auth_headers = {
                **self.base_headers,  # Incluye Bearer token (JOTA_DB_SK)
                "X-Client-ID": settings.ORCHESTRATOR_ID,
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

    async def get_or_create_conversation(self, client_id: int) -> Dict[str, Any]:
        """
        Retrieves active conversation for user_id or creates a new one.
        Returns the conversation object (dict).
        """
        try:
            # Service Auth headers: Orchestrator key + End-Client ID
            service_headers = {
                **self.base_headers,
                "X-API-Key": settings.ORCHESTRATOR_API_KEY,
                "X-Client-ID": str(client_id)
            }
            
            # JotaDB currently doesn't expose a GET /chat/conversation endpoint for clients/services 
            # to list conversations based on status. We create a new one to proceed.
            payload = {"title": "New Chat"} 
            
            create_response = await self.client.post(
                f"{self.base_url}/chat/conversation", 
                json=payload,
                headers=service_headers
            )
            
            if create_response.status_code == 422:
                logger.error(f"422 Error on POST /chat/conversation: {create_response.text}")
            create_response.raise_for_status()
            return create_response.json()

        except Exception as e:
            logger.error(f"Error managing conversation for client {client_id}: {e}")
            raise e

    async def update_conversation_session(self, conversation_id: int, session_id: str, client_id: int):
        """
        Links the JotaDB conversation with the Inference Engine session ID.
        """
        try:
            url = f"{self.base_url}/chat/session"
            payload = {"conversation_id": conversation_id, "inference_session_id": session_id}
            service_headers = {
                **self.base_headers,
                "X-API-Key": settings.ORCHESTRATOR_API_KEY,
                "X-Client-ID": str(client_id)
            }
            response = await self.client.patch(url, json=payload, headers=service_headers)
            if response.status_code == 422:
                logger.error(f"422 Error on PATCH /chat/session: {response.text}")
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to update session ID for conversation {conversation_id}: {e}")
            pass

    async def save_message(self, conversation_id: int, role: Literal["user", "assistant", "system"], content: str, client_id: int):
        """
        Saves a message to JotaDB.
        """
        # Strict validation
        if role not in ["user", "assistant", "system"]:
            logger.error(f"Invalid message role: {role} - Message not saved.")
            return

        try:
            payload = {
                "role": role,
                "content": content
            }
            service_headers = {
                **self.base_headers,
                "X-API-Key": settings.ORCHESTRATOR_API_KEY,
                "X-Client-ID": str(client_id)
            }
            
            # CORRECT ENDPOINT: /chat/{conversation_id}/messages
            url = f"{self.base_url}/chat/{conversation_id}/messages"
            response = await self.client.post(url, json=payload, headers=service_headers)
            if response.status_code == 422:
                logger.error(f"422 Error on POST /chat/{conversation_id}/messages: {response.text}")
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
