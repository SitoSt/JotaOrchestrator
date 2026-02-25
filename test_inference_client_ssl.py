import asyncio
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys

# Mock websockets and pydantic_settings if not available
mock_websockets = MagicMock()
sys.modules["websockets"] = mock_websockets
# websockets.connect is used as 'async with websockets.connect(...)'. 
# It should return a context manager whose __aenter__ returns the websocket.
mock_connect_cm = MagicMock()
mock_ws = AsyncMock()
mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_ws)
mock_connect_cm.__aexit__ = AsyncMock(return_value=None)
mock_websockets.connect = MagicMock(return_value=mock_connect_cm)
mock_websockets.exceptions = MagicMock()
mock_websockets.exceptions.ConnectionClosed = Exception

# Mock httpx
mock_httpx = MagicMock()
sys.modules["httpx"] = mock_httpx

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
        # Reset mocks
        mock_websockets.connect.reset_mock()
        mock_ws.reset_mock()
        
        mock_memory_manager = MagicMock()
        client = InferenceClient(memory_manager=mock_memory_manager, url="wss://test.local")
        
        # Configure mock_ws for this test
        # We need to mock __aiter__ for the loop
        mock_ws.__aiter__.return_value = [
            '{"op": "auth_success", "client_id": "test", "max_sessions": 1}'
        ]
        
        # Since connect() starts a background task, we need to wait a bit
        await client.connect()
        await asyncio.sleep(0.1) # Yield to let background task run
        
        # Check if ssl context was passed
        # websockets.connect.call_args gives us (args, kwargs)
        args, kwargs = mock_websockets.connect.call_args
        self.assertIn("ssl", kwargs)
        self.assertIsNotNone(kwargs["ssl"])
        
        await client.invoke_shutdown()

    async def test_auth_handshake_success(self):
        """Verify auth payload includes jota_db_url and handles success."""
        # Reset mocks
        mock_websockets.connect.reset_mock()
        mock_ws.reset_mock()
        
        mock_memory_manager = MagicMock()
        client = InferenceClient(memory_manager=mock_memory_manager, url="ws://test.local") 
        
        # Mock responses: first auth_success
        mock_ws.__aiter__.return_value = [
                 '{"op": "auth_success", "client_id": "test", "max_sessions": 1}'
        ]
        
        await client.connect()
        await asyncio.sleep(0.1)
        
        # Validate sent payload
        mock_ws.send.assert_called()
        # The first send is auth
        # call_args_list entries are ((arg,), kwargs)
        auth_call_args = [call.args[0] for call in mock_ws.send.call_args_list if call.args and "auth" in call.args[0]]
        self.assertTrue(auth_call_args, "No auth payload sent")
        auth_call = auth_call_args[0]
        self.assertIn('"op": "auth"', auth_call)
        self.assertIn('"jota_db_url"', auth_call)
        self.assertIn(settings.JOTA_DB_URL, auth_call)
        
        await client.invoke_shutdown()

    async def test_auth_handshake_failure(self):
        """Verify exception raised/logged on auth error."""
        # Reset mocks
        mock_websockets.connect.reset_mock()
        mock_ws.reset_mock()
        
        mock_memory_manager = MagicMock()
        client = InferenceClient(memory_manager=mock_memory_manager, url="ws://test.local")
        
        # Mock error response
        mock_ws.__aiter__.return_value = [
                 '{"op": "error", "message": "Invalid API Key"}'
        ]
        
        with patch("src.services.inference.logger") as mock_logger:
            await client.connect()
            await asyncio.sleep(0.1) # Allow task to run and fail
            
            # Check for error log "Authentication failed"
            # mock_logger.error could be called multiple times
            error_logs = [str(call.args[0]) for call in mock_logger.error.call_args_list]
            self.assertTrue(any("Authentication failed" in log for log in error_logs), f"Logs: {error_logs}")
            
        await client.invoke_shutdown()

if __name__ == "__main__":
    unittest.main()
