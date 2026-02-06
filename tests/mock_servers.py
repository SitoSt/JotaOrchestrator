import asyncio
import websockets
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MockServers")

# Mock Transcription Server
async def transcription_handler(websocket):
    logger.info("Client connected to Transcription Server")
    try:
        while True:
            # Simulate silence / waiting
            await asyncio.sleep(5) 
            message = {"text": "Hello Jota, this is a test from transcription."}
            await websocket.send(json.dumps(message))
            logger.info(f"Sent: {message}")
    except websockets.exceptions.ConnectionClosed:
        logger.info("Client disconnected from Transcription Server")

# Mock Inference Server
async def inference_handler(websocket):
    logger.info("Client connected to Inference Server")
    try:
        async for message in websocket:
            data = json.loads(message)
            logger.info(f"Received Inference Request: {data}")
            
            opcode = data.get("opcode")
            if opcode == "infer":
                # Respond with tokens
                response_text = "I heard you. "
                await websocket.send(json.dumps({"opcode": "token", "content": "I "}))
                await asyncio.sleep(0.1)
                await websocket.send(json.dumps({"opcode": "token", "content": "heard "}))
                await asyncio.sleep(0.1)
                await websocket.send(json.dumps({"opcode": "token", "content": "you. "}))
                await asyncio.sleep(0.1)
                await websocket.send(json.dumps({"opcode": "end"}))
    except websockets.exceptions.ConnectionClosed:
        logger.info("Client disconnected from Inference Server")

async def main():
    logger.info("Starting Mock Servers...")
    # Start Transcription Server on 9002
    async with websockets.serve(transcription_handler, "localhost", 9002):
        logger.info("Mock Transcription Server running on ws://localhost:9002")
        
        # Start Inference Server on 9001
        async with websockets.serve(inference_handler, "localhost", 9001):
            logger.info("Mock Inference Server running on ws://localhost:9001")
            
            # Keep alive
            await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
