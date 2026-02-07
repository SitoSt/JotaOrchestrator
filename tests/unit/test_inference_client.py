import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from src.services.inference import InferenceClient
import json
import websockets

@pytest.mark.asyncio
async def test_inference_client_initialization(inference_config):
    """Test that the client initializes with provided config."""
    client = InferenceClient(**inference_config)
    
    assert client.url == inference_config["url"]
    assert client.client_id == inference_config["client_id"]
    assert client.api_key == inference_config["api_key"]
    assert client.websocket is None
    assert client.active_sessions == {}

@pytest.mark.asyncio
async def test_inference_client_defaults(mock_settings):
    """Test that the client initializes with default settings."""
    # We need to make sure settings are mocked if we rely on them
    # But here we are passing explicit None to trigger defaults from settings
    # However, since we import settings at module level in source, 
    # we might need to mock src.core.config.settings instead of env vars if they are already loaded.
    
    # Actually, the refactor uses `url or settings.URL`. 
    # If settings was imported before monkeypatch, it might have old values.
    # But let's assume standard behavior.
    
    with patch("src.services.inference.settings") as mock_conf:
        mock_conf.INFERENCE_SERVICE_URL = "ws://default"
        mock_conf.INFERENCE_CLIENT_ID = "default_id"
        mock_conf.INFERENCE_API_KEY = "default_key"
        
        client = InferenceClient()
        assert client.url == "ws://default"
        assert client.client_id == "default_id"

@pytest.mark.asyncio
async def test_connect_success(inference_config):
    """Test successful connection and authentication."""
    client = InferenceClient(**inference_config)
    
    with patch("src.services.inference.websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_ws = AsyncMock()
        mock_ws.open = True
        mock_connect.return_value = mock_ws
        
        await client.connect()
        
        mock_connect.assert_called_once_with(inference_config["url"])
        assert client.websocket is not None
        
        # Verify auth message
        expected_auth = {
            "op": "auth",
            "client_id": inference_config["client_id"],
            "api_key": inference_config["api_key"]
        }
        mock_ws.send.assert_called_once()
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg == expected_auth

@pytest.mark.asyncio
async def test_connect_failure(inference_config):
    """Test connection failure handling."""
    client = InferenceClient(**inference_config)
    
    with patch("src.services.inference.websockets.connect", side_effect=ConnectionRefusedError("Connection refused")):
        with pytest.raises(ConnectionRefusedError):
            await client.connect()
        
        assert client.websocket is None

@pytest.mark.asyncio
async def test_get_session_creates_new(inference_config):
    """Test creating a new session."""
    client = InferenceClient(**inference_config)
    client.websocket = AsyncMock()
    client.websocket.open = True
    
    # Mock the future to return a session_id immediately (simulating response)
    # But get_session waits for a future that is set by _read_loop.
    # So we need to simulate _read_loop or mock the wait mechanism.
    
    # Since we can't easily run the background task and the main task in lockstep in a simple unit test without a real loop,
    # we can mock asyncio.wait_for or the future itself if possible.
    
    # A better approach for unit testing get_session logic:
    # We can mock asyncio.wait_for to return "session_123" directly.
    
    with patch("asyncio.wait_for", new_callable=AsyncMock) as mock_wait:
        mock_wait.return_value = "session_123"
        
        session_id = await client.get_session("user_1")
        
        assert session_id == "session_123"
        assert client.active_sessions["user_1"] == "session_123"
        
        # Verify "create_session" op was sent
        sent_args = client.websocket.send.call_args_list
        # Triggered connect checks? No providing open websocket.
        # It should send 'create_session'
        assert len(sent_args) > 0
        last_msg = json.loads(sent_args[-1][0][0])
        assert last_msg["op"] == "create_session"

@pytest.mark.asyncio
async def test_get_session_existing(inference_config):
    """Test retrieving an existing session."""
    client = InferenceClient(**inference_config)
    client.active_sessions["user_1"] = "existing_session"
    
    session_id = await client.get_session("user_1")
    assert session_id == "existing_session"
