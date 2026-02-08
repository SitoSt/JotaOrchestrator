#!/usr/bin/env python3
"""
Simple test script to verify the Orchestrator -> Inference Engine connection
"""
import requests
import json

ORCHESTRATOR_URL = "http://localhost:8000"

def test_health():
    """Test basic health endpoint"""
    print("🔍 Testing health endpoint...")
    response = requests.get(f"{ORCHESTRATOR_URL}/health")
    print(f"✅ Health check: {response.json()}")
    return response.status_code == 200

def test_chat_rest():
    """Test chat via REST endpoint"""
    print("\n🔍 Testing chat REST endpoint...")
    payload = {
        "text": "Hola, ¿cómo estás?",
        "session_id": "test_user_123"
    }
    
    print(f"📤 Sending: {payload['text']}")
    response = requests.post(f"{ORCHESTRATOR_URL}/chat", json=payload)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Status: {result.get('status')}")
        print(f"💬 Response: {result.get('response', 'No response')[:200]}...")
        return True
    else:
        print(f"❌ Error: {response.status_code} - {response.text}")
        return False

def main():
    print("=" * 60)
    print("🧪 JotaOrchestrator Connection Test")
    print("=" * 60)
    
    # Test 1: Health
    if not test_health():
        print("❌ Health check failed. Is the orchestrator running?")
        return
    
    # Test 2: Chat
    test_chat_rest()
    
    print("\n" + "=" * 60)
    print("✅ Tests completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
