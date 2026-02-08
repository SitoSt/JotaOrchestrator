#!/usr/bin/env python3
"""
WebSocket test for real-time streaming with the Inference Engine
"""
import asyncio
import websockets
import json

ORCHESTRATOR_WS_URL = "ws://localhost:8000/ws/chat/test_user_456"

async def test_websocket_chat():
    """Test chat via WebSocket for real-time streaming"""
    print("=" * 60)
    print("🧪 WebSocket Streaming Test")
    print("=" * 60)
    
    try:
        print(f"\n🔌 Connecting to {ORCHESTRATOR_WS_URL}...")
        async with websockets.connect(ORCHESTRATOR_WS_URL) as websocket:
            print("✅ Connected!")
            
            # Send a test message
            test_message = "Cuéntame un chiste corto"
            print(f"\n📤 Sending: {test_message}")
            await websocket.send(test_message)
            
            # Receive streaming response
            print("\n💬 Streaming response:")
            print("-" * 60)
            
            full_response = ""
            async for message in websocket:
                print(message, end="", flush=True)
                full_response += message
                
                # Break after reasonable response (optional)
                if len(full_response) > 500:
                    print("\n\n(truncated for demo)")
                    break
            
            print("\n" + "-" * 60)
            print(f"\n✅ Received {len(full_response)} characters")
            
    except websockets.exceptions.ConnectionRefused:
        print("❌ Connection refused. Is the orchestrator running?")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_websocket_chat())
