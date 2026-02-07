import asyncio
import pytest
import time
from src.services.inference import InferenceClient
from tests.integration.mock_server import MockInferenceServer
import random

# Use a separate server for stress tests to avoid interfering with other tests
# and to allow custom behavior if needed.
@pytest.fixture(scope="function")
async def stress_server():
    server = MockInferenceServer(port=8767)
    await server.start()
    yield server
    await server.stop()

@pytest.mark.asyncio
async def test_load_stability(stress_server):
    """
    Simulate a high load of concurrent users.
    """
    NUM_USERS = 50  # adjust as needed
    CONCURRENT_REQUESTS = 10
    
    client = InferenceClient(
        url="ws://localhost:8767",
        client_id="stress_client",
        api_key="stress_key"
    )
    
    await client.connect()
    
    success_count = 0
    error_count = 0
    
    async def simulated_user(user_id):
        nonlocal success_count, error_count
        try:
            # Random delay to simulate real-world usage patterns
            await asyncio.sleep(random.uniform(0.1, 0.5))
            
            tokens = []
            async for token in client.infer(user_id, f"Prompt from {user_id}"):
                tokens.append(token)
            
            if "".join(tokens) == "This is a mock response.":
                success_count += 1
            else:
                error_count += 1
                
        except Exception as e:
            error_count += 1
            print(f"User {user_id} failed: {e}")

    # Run batches of users
    start_time = time.time()
    
    tasks = [simulated_user(f"user_{i}") for i in range(NUM_USERS)]
    await asyncio.gather(*tasks)
    
    duration = time.time() - start_time
    print(f"\nStress Test Results:")
    print(f"Total Users: {NUM_USERS}")
    print(f"Success: {success_count}")
    print(f"Errors: {error_count}")
    print(f"Duration: {duration:.2f}s")
    print(f"RPS (approx): {NUM_USERS / duration:.2f}")
    
    assert error_count == 0
    assert success_count == NUM_USERS

    await client.invoke_shutdown()
