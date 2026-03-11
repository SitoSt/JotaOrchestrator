"""
WebSocket API endpoints for chat operations.

This module handles persistent bi-directional communication with client
applications, allowing real-time token streaming, mid-session control 
messages (e.g., model switching), and context management over a single connection.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from src.core.services import jota_controller, memory_manager, inference_client
import json as _json
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.websocket("/chat/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """
    Handles a full WebSocket chat session.

    Performs sequential actions:
    1. Authenticate client connection.
    2. Manage or create conversation context.
    3. Ensure an Ephemeral Session on the Inference Center.
    4. Recover database context and inject it.
    5. Listen to text inputs and control streams via JSON envelopes.

    Args:
        websocket: The active WebSocket connection.
        user_id: The ID of the connecting user.
    """
    # 1. Authentication
    # Allow passing auth token via query params for simpler WebSocket clients
    client_key = websocket.headers.get("x-client-key") or websocket.query_params.get("x_client_key") or websocket.query_params.get("client_key")
    if not client_key:
        logger.warning(f"Missing Client Key header or query param for user {user_id}")
        await websocket.close(code=4001, reason="Unauthorized")
        return
        
    client_data = await memory_manager.validate_client_key(client_key)
    if not client_data:
        logger.warning(f"Unauthorized access attempt for user {user_id}")
        await websocket.close(code=4001, reason="Unauthorized")
        return
        
    # 2. Validar tipo de cliente
    client_type = client_data.get("client_type", "chat")
    if client_type == "quick":
        logger.warning(f"QUICK client {client_data['id']} attempted WS connection")
        await websocket.close(code=4003, reason="Client type 'quick' not allowed on WebSocket")
        return
        
    client_id = client_data["id"]

    await websocket.accept()
    logger.info(f"WebSocket connected for user {user_id}")

    # Fail fast if Engine is not connected
    if not inference_client.is_connected:
        logger.error(f"Inference Engine not connected — closing WS for {user_id}")
        await websocket.send_text(_json.dumps({
            "type": "error",
            "message": "Inference Engine no disponible. Intenta de nuevo en unos segundos."
        }))
        await websocket.close(code=1011, reason="Inference Engine not connected")
        return
    
    try:
        # 2. Conversation Management
        conversation_id = websocket.query_params.get("conversation_id")
        model_id = websocket.query_params.get("model_id") or None
        if not conversation_id:
            conversation = await memory_manager.create_conversation(
                user_id, client_id=client_id, model_id=model_id
            )
            conversation_id = conversation["id"]
            logger.info(
                f"[TRACE][Conv: {conversation_id}] New conversation created "
                f"for user={user_id} model_id={model_id!r}"
            )
        elif model_id:
            # Client reconnected with an existing conversation and a new model_id.
            # switch_model atomically loads in engine + updates DB.
            logger.info(
                f"[TRACE][Conv: {conversation_id}] Reconnect with model change — "
                f"engine_current={inference_client.current_engine_model!r} "
                f"→ requested={model_id!r}. Calling switch_model."
            )
            await jota_controller.switch_model(conversation_id, client_id, model_id)
        else:
            logger.info(
                f"[TRACE][Conv: {conversation_id}] Reconnect without model change "
                f"(engine_current={inference_client.current_engine_model!r})."
            )

        # 3. Ephemeral Session (aborts previous if exists)
        session_id = await inference_client.ensure_session(user_id)

        # 4. Recover context from DB and inject into session
        context = await memory_manager.get_conversation_messages(conversation_id, client_id)
        await inference_client.set_context(session_id, context)

        log_prefix = f"[Conv: {conversation_id}][Sess: {session_id}]"
        logger.info(f"{log_prefix} Session ready. Waiting for messages...")

        while True:
            data = await websocket.receive_text()
            logger.info(f"{log_prefix} Received via WS: {data}")

            # -- Control message: JSON envelope with "type" field --
            # Allows mid-session operations without reconnecting.
            try:
                ctrl = _json.loads(data)
                if isinstance(ctrl, dict) and "type" in ctrl:
                    msg_type = ctrl["type"]

                    if msg_type == "switch_model":
                        new_model = ctrl.get("model_id", "").strip()
                        if not new_model:
                            await websocket.send_text(_json.dumps({
                                "type": "error",
                                "message": "switch_model requires a non-empty model_id"
                            }))
                            continue
                        logger.info(
                            f"{log_prefix} [TRACE] Mid-session switch_model requested: "
                            f"{model_id!r} → {new_model!r}"
                        )
                        try:
                            await jota_controller.switch_model(conversation_id, client_id, new_model)
                            model_id = new_model  # update local var for next infer
                            await websocket.send_text(_json.dumps({
                                "type": "model_switched",
                                "model_id": new_model
                            }))
                            logger.info(
                                f"{log_prefix} [TRACE] switch_model OK mid-session — "
                                f"new engine_current={inference_client.current_engine_model!r}"
                            )
                        except Exception as sw_err:
                            logger.error(f"{log_prefix} switch_model failed: {sw_err}")
                            await websocket.send_text(_json.dumps({
                                "type": "error",
                                "message": str(sw_err)
                            }))
                        continue  # don't treat this as a prompt

                    # Unknown control type — log and ignore
                    logger.warning(f"{log_prefix} Unknown control message type: {msg_type!r}")
                    await websocket.send_text(_json.dumps({
                        "type": "error",
                        "message": f"Unknown control type: {msg_type!r}"
                    }))
                    continue
            except _json.JSONDecodeError:
                pass  # plain text prompt — fall through

            # 5. Save User Message (text prompt)
            await memory_manager.save_message(
                conversation_id=conversation_id,
                user_id=user_id,
                role="user",
                content=data,
                client_id=client_id
            )

            payload = {
                "content": data,
                "session_id": session_id,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "client_id": client_id,
                "model_id": model_id,
                "source": "websocket"
            }

            logger.info(
                f"{log_prefix} [TRACE] Dispatching to controller — "
                f"db_model={model_id!r} engine_model={inference_client.current_engine_model!r}"
            )

            # 6. Stream tokens back
            async for token in jota_controller.handle_input(payload):
                if isinstance(token, dict):
                    # Structured control message (e.g. status indicator)
                    await websocket.send_text(_json.dumps(token))
                else:
                    # Plain text content token
                    await websocket.send_text(_json.dumps({"type": "token", "content": token}))
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id}")

    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        await websocket.close(code=1011)

    finally:
        # Always release session on any exit path
        await inference_client.release_session(user_id)
