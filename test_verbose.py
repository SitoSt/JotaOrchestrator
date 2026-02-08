#!/usr/bin/env python3
"""
Detailed test with verbose logging
"""
import requests
import json
import logging

logging.basicConfig(level=logging.DEBUG)

ORCHESTRATOR_URL = "http://localhost:8000"

def test_chat_verbose():
    """Test chat with detailed output"""
    print("=" * 60)
    print("🧪 Detailed Chat Test")
    print("=" * 60)
    
    payload = {
        "text": "Di solo: Hola mundo",
        "session_id": "test_verbose_001"
    }
    
    print(f"\n📤 Request:")
    print(json.dumps(payload, indent=2))
    
    try:
        response = requests.post(
            f"{ORCHESTRATOR_URL}/chat", 
            json=payload,
            timeout=30
        )
        
        print(f"\n📥 Response Status: {response.status_code}")
        print(f"📥 Response Headers: {dict(response.headers)}")
        print(f"\n📥 Response Body:")
        print(json.dumps(response.json(), indent=2))
        
    except requests.exceptions.Timeout:
        print("❌ Request timed out (30s)")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_chat_verbose()
