import asyncio
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys

# Mock websockets and pydantic_settings if not available
mock_websockets = MagicMock()
sys.modules["websockets"] = mock_websockets
mock_websockets.connect = AsyncMock()
mock_websockets.exceptions = MagicMock()
mock_websockets.exceptions.ConnectionClosed = Exception

# Mock pydantic_settings if needed, though config might be needed
# Mock pydantic_settings if needed
try:
    import pydantic_settings
except ImportError:
    mock_pydantic_settings = MagicMock()
    sys.modules["pydantic_settings"] = mock_pydantic_settings
    
    class BaseSettings:
        def __init__(self, **kwargs):
            self.INFERENCE_SERVICE_URL = "ws://test.local"
            self.INFERENCE_CLIENT_ID = "test_id"
            self.INFERENCE_API_KEY = "test_key"
            self.SSL_VERIFY = True
            self.JOTA_DB_URL = "postgresql://test"
            self.TRANSCRIPTION_SERVICE_URL = "ws://test"
            # Add other required fields if any
            self.APP_NAME = "TestApp"
            self.APP_ENV = "test"
            self.DEBUG = True
            
        class Config:
             env_file = ".env"
    
    mock_pydantic_settings.BaseSettings = BaseSettings

# Import modules
from src.services.inference import InferenceClient
from src.core.config import settings

class TestInferenceClientSSL(unittest.IsolatedAsyncioTestCase):
    async def test_connect_wss_ssl_context(self):
        """Verify that WSS URL triggers SSL context creation."""
        with patch("src.services.inference.websockets.connect", new_callable=AsyncMock) as mock_connect:
            client = InferenceClient(url="wss://test.local")
            
            # Mock the websocket instance returned by connect
            mock_ws = AsyncMock()
            mock_connect.return_value = mock_ws
            
            # Mock receiving auth_success immediately
            async def mock_recv():
                return '{"op": "auth_success", "client_id": "test", "max_sessions": 1}'
            
            # We need to mock __aiter__ for the loop
            mock_ws.__aiter__.return_value = [
                '{"op": "auth_success", "client_id": "test", "max_sessions": 1}'
            ]
            
            await client.connect()
            
            # Check if ssl context was passed
            args, kwargs = mock_connect.call_args
            self.assertIn("ssl", kwargs)
            self.assertIsNotNone(kwargs["ssl"])

    async def test_auth_handshake_success(self):
        """Verify auth payload includes jota_db_url and handles success."""
        with patch("src.services.inference.websockets.connect", new_callable=AsyncMock) as mock_connect:
            client = InferenceClient(url="ws://test.local") 
            mock_ws = AsyncMock()
            mock_connect.return_value = mock_ws
            
            # Mock responses: first auth_success, then maybe something else or end
            mock_ws.__aiter__.return_value = [
                 '{"op": "auth_success", "client_id": "test", "max_sessions": 1}'
            ]
            
            await client.connect()
            
            # Validate sent payload
            mock_ws.send.assert_called()
            call_args = mock_ws.send.call_args[0][0]
            self.assertIn('"op": "auth"', call_args)
            self.assertIn('"jota_db_url"', call_args)
            self.assertIn(settings.JOTA_DB_URL, call_args)

    async def test_auth_handshake_failure(self):
        """Verify exception raised on auth error."""
        with patch("src.services.inference.websockets.connect", new_callable=AsyncMock) as mock_connect:
            client = InferenceClient(url="ws://test.local")
            mock_ws = AsyncMock()
            mock_connect.return_value = mock_ws
            
            # Mock error response
            mock_ws.__aiter__.return_value = [
                 '{"op": "error", "message": "Invalid API Key"}'
            ]
            
            with self.assertRaisesRegex(ConnectionError, "Authentication failed"):
                await client.connect()

if __name__ == "__main__":
    unittest.main()
