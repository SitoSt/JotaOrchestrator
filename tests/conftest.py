import pytest
import asyncio
import os

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def mock_settings(monkeypatch):
    """Mock environment variables for testing."""
    monkeypatch.setenv("INFERENCE_SERVICE_URL", "ws://localhost:8000/ws")
    monkeypatch.setenv("INFERENCE_CLIENT_ID", "test_client")
    monkeypatch.setenv("INFERENCE_API_KEY", "test_key")

@pytest.fixture
def inference_config():
    return {
        "url": "ws://test-server",
        "client_id": "unit-test-client",
        "api_key": "unit-test-key"
    }
