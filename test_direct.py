#!/usr/bin/env python3
"""
Direct test of the inference client
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, '/home/sito/JotaOrchestrator')

from src.services.inference import inference_client
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_direct_inference():
    """Test inference client directly"""
    print("=" * 60)
    print("🧪 Direct Inference Client Test")
    print("=" * 60)
    
    try:
        # Connect
        print("\n1️⃣ Connecting to inference engine...")
        await inference_client.connect()
        print("✅ Connected!")
        
        # Test inference
        print("\n2️⃣ Sending inference request...")
        user_id = "test_direct_user"
        prompt = "Di solo: Hola"
        
        print(f"   User ID: {user_id}")
        print(f"   Prompt: {prompt}")
        print("\n3️⃣ Streaming response:")
        print("-" * 60)
        
        full_response = ""
        async for token in inference_client.infer(user_id, prompt):
            print(token, end="", flush=True)
            full_response += token
        
        print("\n" + "-" * 60)
        print(f"\n✅ Complete! Received {len(full_response)} characters")
        print(f"   Full response: {full_response}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        if inference_client.websocket:
            await inference_client.websocket.close()

if __name__ == "__main__":
    asyncio.run(test_direct_inference())
