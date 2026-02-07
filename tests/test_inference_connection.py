import asyncio
import websockets
import json
import os
from dotenv import load_dotenv

load_dotenv()

async def test_connection():
    url = os.getenv("INFERENCE_SERVICE_URL")
    client_id = os.getenv("INFERENCE_CLIENT_ID")
    api_key = os.getenv("INFERENCE_API_KEY")
    
    print(f"Testing connection to: {url}")
    
    try:
        async with websockets.connect(url) as websocket:
            print("✅ WebSocket Connected!")
            
            # 1. Send Auth immediately
            auth_payload = {
                "op": "auth",
                "client_id": client_id,
                "api_key": api_key
            }
            await websocket.send(json.dumps(auth_payload))
            print("➡️ Sent Auth.")

            # 2. Send Create Session
            await websocket.send(json.dumps({"op": "create_session"}))
            print("➡️ Sent Create Session.")
            
            # 3. Read loop to see what happens
            print("Listening for responses...")
            while True:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    data = json.loads(response)
                    op = data.get("op")
                    print(f"⬅️ Received: {data}")
                    
                    if op == "session_created":
                        print(f"✅ SUCCESS: Session {data.get('session_id')} created!")
                        return
                    elif op == "auth_success": # If protocol has this
                        print("✅ Auth confirmed.")
                    elif op == "error":
                        print(f"❌ Server Error: {data.get('message')}")
                        return
                        
                except asyncio.TimeoutError:
                    print("❌ Timeout waiting for session_created.")
                    break
                
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
