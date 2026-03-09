# Guía de Implementación: Clientes QUICK vs CHAT

## Visión General

Esta guía detalla cómo implementar la separación de responsabilidades entre dos tipos de clientes en JotaOrchestrator:

| Característica | QUICK | CHAT |
|----------------|-------|------|
| **Propósito** | Comandos rápidos, respuestas cortas | Conversación completa |
| **Estado** | Stateless (sin contexto) | Stateful (contexto completo) |
| **Persistencia** | No guarda mensajes | Guarda en JotaDB |
| **Streaming** | No (respuesta completa) | Sí (tokens en tiempo real) |
| **Casos de uso** | Domótica, búsquedas, timers | Conversación libre |

---

## PASO 1: Endpoint `/quick` Básico

### 1.1 Crear el archivo `src/api/quick.py`

```python
"""
quick.py
~~~~~~~~
Endpoint REST para clientes QUICK: comandos rápidos, stateless, sin streaming.
"""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

from src.core.services import inference_client, memory_manager
from src.core.tool_manager import tool_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# System prompt optimizado para respuestas cortas y directas
QUICK_SYSTEM_PROMPT = """Eres J, un asistente virtual eficiente.
REGLAS ESTRICTAS:
- Responde en 1-3 frases máximo
- Sin explicaciones innecesarias
- Directo al grano
- Para comandos, confirma con una palabra o frase corta
- Para búsquedas, resume los puntos clave brevemente

Ejemplos:
- "Enciende la luz del salón" → "Luz del salón encendida."
- "¿Qué tiempo hace en Madrid?" → "Madrid: 18°C, parcialmente nublado."
- "Pon un timer de 5 minutos" → "Timer de 5 minutos iniciado."
"""


class QuickRequest(BaseModel):
    """Petición para el endpoint QUICK."""
    text: str
    user_id: str = "quick_user"


class QuickResponse(BaseModel):
    """Respuesta del endpoint QUICK."""
    status: str
    response: str
    execution_time_ms: Optional[float] = None


@router.post("/quick", response_model=QuickResponse)
async def quick_endpoint(
    request: QuickRequest,
    x_client_key: str = Header(..., description="Client authentication key")
):
    """
    Endpoint para comandos rápidos y respuestas cortas.
    
    Características:
    - Stateless: no guarda contexto ni mensajes
    - Sin streaming: devuelve respuesta completa
    - Optimizado para respuestas cortas (max_tokens reducido)
    - System prompt específico para brevedad
    """
    import time
    start_time = time.time()
    
    # 1. Autenticación
    client_data = await memory_manager.validate_client_key(x_client_key)
    if not client_data:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # 2. Verificar que el cliente es de tipo QUICK
    client_type = client_data.get("client_type", "chat")  # default a chat por compatibilidad
    if client_type != "quick":
        raise HTTPException(
            status_code=403, 
            detail=f"Client type '{client_type}' not allowed on /quick endpoint. Expected 'quick'."
        )
    
    client_id = client_data["id"]
    log_prefix = f"[QUICK][Client: {client_id}]"
    
    try:
        logger.info(f"{log_prefix} Processing: {request.text[:50]}...")
        
        # 3. Crear sesión efímera (sin tracking por user_id)
        session_id = await inference_client.create_session()
        
        # 4. Preparar prompt con system prompt QUICK
        tool_instructions = tool_manager.get_system_prompt_addition()
        
        full_prompt = f"{QUICK_SYSTEM_PROMPT}\n"
        if tool_instructions:
            full_prompt += f"\n{tool_instructions}\n"
        full_prompt += f"\nUsuario: {request.text}"
        
        # 5. Parámetros optimizados para respuestas cortas
        quick_params = {
            "temp": 0.3,        # Menos creatividad, más determinismo
            "max_tokens": 150,  # Límite de tokens reducido
        }
        
        # 6. Inferencia (acumulamos tokens sin streaming al cliente)
        full_response = ""
        async for token in inference_client.infer(
            session_id=session_id,
            prompt=full_prompt,
            conversation_id=f"quick_{session_id}",  # ID temporal
            user_id=request.user_id,
            params=quick_params,
            client_id=client_id,
            model_id=None,  # Usa el modelo cargado actualmente
        ):
            if isinstance(token, dict):
                # Tool calls - por ahora los procesamos inline
                if token.get("type") == "tool_call":
                    # TODO: Implementar tool execution para QUICK
                    logger.info(f"{log_prefix} Tool call detected (not yet implemented)")
                continue
            full_response += token
        
        # 7. Cerrar sesión inmediatamente (stateless)
        await inference_client.close_session(session_id)
        
        execution_time = (time.time() - start_time) * 1000
        logger.info(f"{log_prefix} Completed in {execution_time:.0f}ms")
        
        return QuickResponse(
            status="success",
            response=full_response.strip(),
            execution_time_ms=round(execution_time, 2)
        )
        
    except Exception as e:
        logger.error(f"{log_prefix} Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

### 1.2 Registrar el router en `src/main.py`

Añade estas líneas en `main.py`:

```python
# Importar el nuevo router (junto a los otros imports)
from src.api.quick import router as quick_router

# Registrar el router (junto al chat_router existente)
app.include_router(quick_router)
```

**Ubicación exacta en tu archivo actual:**

```python
# Línea ~7: Añadir import
from src.api.chat import router as chat_router
from src.api.quick import router as quick_router  # ← AÑADIR

# Línea ~67: Añadir router
app.include_router(chat_router)
app.include_router(quick_router)  # ← AÑADIR
```

### 1.3 Modificar `inference.py` para soportar NO persistencia

El método `infer()` actual siempre guarda mensajes. Necesitamos un parámetro para desactivarlo.

**En `src/services/inference.py`, modifica la firma de `infer()`:**

```python
async def infer(
    self,
    session_id: str,
    prompt: str,
    conversation_id: str,
    user_id: str,
    params: Optional[Dict[str, Any]] = None,
    client_id: int = None,
    model_id: Optional[str] = None,
    persist_messages: bool = True,  # ← AÑADIR este parámetro
) -> AsyncGenerator[Any, None]:
```

**Y modifica las llamadas a `save_message` para que sean condicionales:**

```python
# Donde dice (aprox línea 380):
await self.memory_manager.save_message(
    conversation_id=conversation_id,
    user_id=user_id,
    role="assistant",
    content=full_response,
    client_id=client_id,
    metadata={"model_id": model_id} if model_id else None,
)

# Cámbialo por:
if persist_messages:
    await self.memory_manager.save_message(
        conversation_id=conversation_id,
        user_id=user_id,
        role="assistant",
        content=full_response,
        client_id=client_id,
        metadata={"model_id": model_id} if model_id else None,
    )
```

**Haz lo mismo para el guardado de respuestas parciales (aprox línea 395).**

### 1.4 Actualizar la llamada en `quick.py`

```python
# En quick.py, la llamada a infer queda:
async for token in inference_client.infer(
    session_id=session_id,
    prompt=full_prompt,
    conversation_id=f"quick_{session_id}",
    user_id=request.user_id,
    params=quick_params,
    client_id=client_id,
    model_id=None,
    persist_messages=False,  # ← NO persistir mensajes QUICK
):
```

---

## PASO 2: Validación por Tipo de Cliente

### 2.1 Esquema de Base de Datos (JotaDB)

Necesitas añadir un campo `client_type` a la tabla de clientes en JotaDB.

**Valores posibles:**
- `"quick"` - Solo puede usar `/quick`
- `"chat"` - Solo puede usar `/ws/chat` y `/chat`
- `"hybrid"` (futuro) - Puede usar ambos

**SQL de migración (si usas PostgreSQL/SQLite):**

```sql
ALTER TABLE clients 
ADD COLUMN client_type VARCHAR(10) DEFAULT 'chat' NOT NULL;

-- Índice para búsquedas rápidas
CREATE INDEX idx_clients_type ON clients(client_type);
```

### 2.2 Actualizar el endpoint de validación en JotaDB

El endpoint `/auth/client` debe devolver el `client_type` junto con el `id`:

```json
// Respuesta actual:
{"id": 123}

// Respuesta nueva:
{"id": 123, "client_type": "quick"}
```

### 2.3 Añadir validación de tipo en `src/api/chat.py`

**En el endpoint `POST /chat`:**

```python
@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    x_client_key: str = Header(..., description="Client authentication key")
):
    # 1. Authentication
    client_data = await memory_manager.validate_client_key(x_client_key)
    if not x_client_key or not client_data:
        return {"status": "error", "message": "Unauthorized"}
    
    # 2. Validar tipo de cliente ← AÑADIR
    client_type = client_data.get("client_type", "chat")
    if client_type == "quick":
        return {
            "status": "error", 
            "message": "Client type 'quick' not allowed on /chat endpoint. Use /quick instead."
        }
    
    client_id = client_data["id"]
    # ... resto del código igual
```

**En el WebSocket `/ws/chat/{user_id}`:**

```python
@router.websocket("/ws/chat/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    # 1. Authentication
    client_key = websocket.headers.get("x-client-key") or ...
    
    client_data = await memory_manager.validate_client_key(client_key)
    if not client_data:
        await websocket.close(code=4001, reason="Unauthorized")
        return
    
    # 2. Validar tipo de cliente ← AÑADIR
    client_type = client_data.get("client_type", "chat")
    if client_type == "quick":
        logger.warning(f"QUICK client {client_data['id']} attempted WS connection")
        await websocket.close(code=4003, reason="Client type 'quick' not allowed on WebSocket")
        return
    
    client_id = client_data["id"]
    await websocket.accept()
    # ... resto del código igual
```

### 2.4 Códigos de cierre WebSocket personalizados

| Código | Significado |
|--------|-------------|
| `4001` | Unauthorized (client_key inválido) |
| `4003` | Forbidden (tipo de cliente no permitido) |

---

## Resumen de Archivos a Modificar/Crear

### Archivos NUEVOS:
```
src/api/quick.py          ← Crear (endpoint /quick)
```

### Archivos a MODIFICAR:

```
src/main.py                ← Añadir import y router de quick
src/services/inference.py  ← Añadir parámetro persist_messages
src/api/chat.py            ← Añadir validación de client_type
```

### En JotaDB (externo):
```
- Migración SQL: añadir columna client_type
- Endpoint /auth/client: devolver client_type en respuesta
```

---

## Testing

### Test manual del endpoint QUICK:

```bash
# Crear un cliente de tipo QUICK en JotaDB primero

# Test básico
curl -X POST http://localhost:8000/quick \
  -H "Content-Type: application/json" \
  -H "x-client-key: TU_QUICK_CLIENT_KEY" \
  -d '{"text": "Pon un timer de 5 minutos", "user_id": "test"}'

# Respuesta esperada:
{
  "status": "success",
  "response": "Timer de 5 minutos iniciado.",
  "execution_time_ms": 245.32
}
```

### Test de rechazo (cliente QUICK en endpoint CHAT):

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "x-client-key: TU_QUICK_CLIENT_KEY" \
  -d '{"text": "Hola", "user_id": "test"}'

# Respuesta esperada:
{
  "status": "error",
  "message": "Client type 'quick' not allowed on /chat endpoint. Use /quick instead."
}
```

---

## Diagrama de Flujo Final

```
                         ┌──────────────────────────────────┐
                         │        validate_client_key       │
                         │   → returns {id, client_type}    │
                         └──────────────┬───────────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                   │                   │
                    ▼                   ▼                   ▼
            client_type="quick"  client_type="chat"  client_type="hybrid"
                    │                   │                   │
        ┌───────────┴───────────┐       │           (futuro)│
        │                       │       │                   │
        ▼                       ▼       ▼                   │
   POST /quick              RECHAZAR   POST /chat           │
   ✓ Permitido              403/4003   WS /ws/chat          │
                                       ✓ Permitido          │
                                                            │
                                                   Ambos endpoints
                                                   ✓ Permitidos
```

---

## Notas Adicionales

1. **El parámetro `persist_messages=False`** en QUICK evita escribir en JotaDB, reduciendo latencia.

2. **El system prompt QUICK** es crucial para obtener respuestas cortas. Ajústalo según tus necesidades.

3. **Los parámetros de inferencia** (`temp: 0.3`, `max_tokens: 150`) están optimizados para comandos. Puedes ajustarlos.

4. **Para el futuro híbrido**, podrías añadir un campo `allowed_endpoints: ["quick", "chat"]` en lugar de `client_type` para más flexibilidad.