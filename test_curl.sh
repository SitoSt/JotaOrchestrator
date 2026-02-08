#!/bin/bash
# Simple test script using curl

echo "============================================================"
echo "🧪 JotaOrchestrator Connection Test (curl)"
echo "============================================================"

echo ""
echo "1️⃣ Testing health endpoint..."
curl -s http://localhost:8000/health | jq '.'

echo ""
echo "2️⃣ Testing chat endpoint..."
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"text": "Di solo: Hola mundo", "session_id": "test_bash_001"}' | jq '.'

echo ""
echo "============================================================"
echo "✅ Tests completed!"
echo "============================================================"
