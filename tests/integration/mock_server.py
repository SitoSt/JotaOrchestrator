import asyncio
import websockets
import json
import logging

logger = logging.getLogger(__name__)

class MockInferenceServer:
    def __init__(self, host="localhost", port=8765):
        self.host = host
        self.port = port
        self.server = None
        self.clients = set()

    async def start(self):
        self.server = await websockets.serve(self.handler, self.host, self.port)
        logger.info(f"Mock Server started on ws://{self.host}:{self.port}")

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("Mock Server stopped")

    async def handler(self, websocket):
        self.clients.add(websocket)
        try:
            async for message in websocket:
                data = json.loads(message)
                op = data.get("op")
                
                if op == "auth":
                    # Simulate auth check
                    if data.get("api_key") == "invalid":
                         await websocket.send(json.dumps({
                            "op": "error",
                            "message": "Authentication failed"
                        }))
                    # else silent success or custom ack if protocol demanded it
                    pass

                elif op == "create_session":
                    # Return a random session ID
                    session_id = "mock_session_123"
                    await websocket.send(json.dumps({
                        "op": "session_created",
                        "session_id": session_id
                    }))

                elif op == "infer":
                    session_id = data.get("session_id")
                    prompt = data.get("prompt")
                    
                    # Stream some mock tokens
                    tokens = ["This", " is", " a", " mock", " response", "."]
                    for token in tokens:
                        await asyncio.sleep(0.01) # Simulate latency
                        await websocket.send(json.dumps({
                            "op": "token",
                            "session_id": session_id,
                            "content": token
                        }))
                    
                    # Send end
                    await websocket.send(json.dumps({
                        "op": "end",
                        "session_id": session_id
                    }))

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.remove(websocket)

if __name__ == "__main__":
    # For manual running
    logging.basicConfig(level=logging.INFO)
    server = MockInferenceServer()
    asyncio.run(server.start())
    asyncio.get_event_loop().run_forever()
