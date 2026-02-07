import pytest
import asyncio
import pytest_asyncio
from src.services.inference import InferenceClient
from tests.integration.mock_server import MockInferenceServer

# Start the mock server fixture
@pytest_asyncio.fixture(scope="function")
async def mock_server():
    server = MockInferenceServer(port=8766) # Use different port than default
    await server.start()
    yield server
    await server.stop()

@pytest.mark.asyncio
async def test_full_inference_flow(mock_server):
    """
    Test the complete flow: 
    Connect -> Auth -> Create Session -> Infer -> Receive Tokens
    """
    client = InferenceClient(
        url="ws://localhost:8766",
        client_id="test_client",
        api_key="test_key"
    )

    try:
        # 1. Connect
        await client.connect()
        assert client.websocket is not None
        assert client.websocket.open

        # 2. Get Session (triggers send create_session and waits for response)
        session_id = await client.get_session("user_test_1")
        assert session_id == "mock_session_123"
        
        # 3. Infer
        prompt = "Hello"
        received_tokens = []
        
        async for token in client.infer("user_test_1", prompt):
            received_tokens.append(token)
        
        # Verify we got tokens
        assert len(received_tokens) > 0
        assert "".join(received_tokens) == "This is a mock response."

    finally:
        # Cleanup
        if client.websocket:
            await client.websocket.close()
        # Also stop the reader task to avoid warnings
        await client.invoke_shutdown()

@pytest.mark.asyncio
async def test_concurrent_sessions(mock_server):
    """
    Test multiple concurrent inference sessions.
    """
    client = InferenceClient(
        url="ws://localhost:8766",
        client_id="test_client",
        api_key="test_key"
    )
    
    await client.connect()
    
    async def run_session(user_id):
        tokens = []
        async for token in client.infer(user_id, "prompt"):
            tokens.append(token)
        return "".join(tokens)

    # Run 3 concurrent sessions
    results = await asyncio.gather(
        run_session("user_1"),
        run_session("user_2"),
        run_session("user_3")
    )
    
    for res in results:
        assert res == "This is a mock response."
        
    await client.invoke_shutdown()
