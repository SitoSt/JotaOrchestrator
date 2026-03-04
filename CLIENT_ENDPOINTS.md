# JotaOrchestrator — Documentación de Endpoints para Clientes


## Tabla de Contenidos

1. [Autenticación y Credenciales](#autenticación-y-credenciales)
2. [Flujo General de Uso](#flujo-general-de-uso)  
3. [Endpoints de Sistema](#endpoints-de-sistema)  
   - `GET /` — Raíz  
   - `GET /health` — Health Check  
4. [Endpoints de Modelos](#endpoints-de-modelos)  
   - `GET /chat/models` — Listar modelos *(nuevo)*  
5. [Endpoints de Conversaciones](#endpoints-de-conversaciones)  
   - `GET /chat/conversations/{user_id}` — Listar conversaciones  
   - `GET /chat/conversations/{user_id}/{conversation_id}/messages` — Mensajes de conversación  
   - `PATCH /chat/conversations/{conversation_id}` — Cambiar modelo de conversación *(nuevo)*  
6. [Endpoints de Chat](#endpoints-de-chat)  
   - `POST /chat` — Chat REST (sin streaming)  
   - `WebSocket /ws/chat/{user_id}` — Chat en tiempo real (streaming)  
7. [Códigos de Error y Respuestas de Error](#códigos-de-error-y-respuestas-de-error)
8. [Notas de Implementación y Limitaciones](#notas-de-implementación-y-limitaciones)

---

## Autenticación y Credenciales

Todos los endpoints (excepto `/` y `/health`) requieren autenticación como **cliente externo**.  
JotaOrchestrator distingue dos tipos de credenciales:

| Tipo | Quién la usa | Mecanismo |
|------|-------------|-----------|
| **Client Key** (`x-client-key`) | Aplicaciones cliente externas | Header HTTP / Query param WebSocket |
| **Orchestrator Key** (`ORCHESTRATOR_ID` + `ORCHESTRATOR_API_KEY`) | Comunicación interna Orchestrator ↔ InferenceEngine | Headers WebSocket internos — **nunca expuesta al cliente** |

### Client Key

- **Header:** `x-client-key: <tu_clave_de_cliente>`
- **Para WebSocket:** puede pasarse como query param `?x_client_key=<clave>` o `?client_key=<clave>` (para clientes que no soporten cabeceras personalizadas en la apertura del WebSocket).
- La clave se valida contra JotaDB en cada petición. Si es inválida o falta → `401 Unauthorized`.
- La validación devuelve internamente el `client_id` numérico, que se usa para aislar los datos de cada cliente (las conversaciones y mensajes pertenecen al `client_id`, no solo al `user_id`).

### Variables de Entorno del Servidor

El archivo `.env` del Orchestrator debe contener:

```env
ORCHESTRATOR_ID=<id_interno_del_orchestrator>
ORCHESTRATOR_API_KEY=<clave_interna>
JOTA_DB_URL=https://...
JOTA_DB_SK=<server_key_para_jotadb>
INFERENCE_SERVICE_URL=ws(s)://...
SSL_VERIFY=true          # false si usas certificados auto-firmados en desarrollo
```

> ⚠️ El cliente **nunca** debe conocer `ORCHESTRATOR_API_KEY` ni `JOTA_DB_SK`. Éstas son credenciales de servicio interno.

---

## Flujo General de Uso

### Flujo WebSocket (recomendado — streaming)

```
Cliente                       JotaOrchestrator              JotaDB           InferenceEngine
  │                                   │                        │                    │
  │── WS /ws/chat/{user_id}          │                        │                    │
  │   ?conversation_id=<id>          │                        │                    │
  │   ?model_id=<model>              │                        │                    │
  │   Header: x-client-key=<key>     │                        │                    │
  │──────────────────────────────────>│                        │                    │
  │                                   │── validate_client_key ──>│                  │
  │                                   │<── {id: client_id} ─────│                  │
  │                                   │── create_conversation ──>│                  │  (si no hay conversation_id)
  │                                   │<── {id: conv_id} ───────│                  │
  │                                   │── ensure_session ────────────────────────────>│
  │                                   │<── session_id ───────────────────────────────│
  │                                   │── get_messages (contexto) ──>│              │
  │                                   │── set_context ───────────────────────────────>│
  │<── WS accept ─────────────────────│                        │                    │
  │                                   │                        │                    │
  │── "Hola, ¿cómo estás?" ──────────>│                        │                    │
  │                                   │── save_message(user) ───>│                  │
  │                                   │── infer(prompt) ─────────────────────────────>│
  │<── "Hola! Estoy" ─────────────────│<── token ────────────────────────────────────│
  │<── " bien, gracias." ─────────────│<── token ────────────────────────────────────│
  │<── [fin]  ────────────────────────│<── end ─────────────────────────────────────│
  │                                   │── save_message(assistant)──>│               │
  │                                   │                        │                    │
  │── [desconecta] ──────────────────>│                        │                    │
  │                                   │── release_session ───────────────────────────>│
```

### Flujo REST (sin streaming)

```
Cliente                       JotaOrchestrator              JotaDB           InferenceEngine
  │                                   │                        │                    │
  │── POST /chat ────────────────────>│                        │                    │
  │   Header: x-client-key            │                        │                    │
  │   Body: {text, user_id, model_id} │                        │                    │
  │                                   │── validate_client_key ──>│                  │
  │                                   │── create_conversation ──>│                  │
  │                                   │── ensure_session ────────────────────────────>│
  │                                   │── set_context ───────────────────────────────>│
  │                                   │── save_message(user) ───>│                  │
  │                                   │── infer (streaming interno) ─────────────────>│
  │                                   │                        │                    │
  │                                   │   [Si detecta <tool_call>]                   │
  │                                   │── execute_tool (Tavily/MCP) ──────────────>  │
  │                                   │── save_message(tool) ───>│                  │
  │                                   │── RE-INFER (contexto actualizado) ───────────>│
  │                                   │                        │                    │
  │                                   │◄─ tokens ... end ───────────────────────────│
  │                                   │── save_message(assistant)──>│               │
  │                                   │── release_session ───────────────────────────>│
  │<── {status, response: "..."} ─────│                        │                    │
```

### Flujo de gestión de modelo

```
Cliente                       JotaOrchestrator              JotaDB           InferenceEngine
  │                                   │                        │                    │
  │── GET /chat/models ──────────────>│                        │                    │
  │   Header: x-client-key            │                        │                    │
  │                                   │── COMMAND_LIST_MODELS ────────────────────── >│
  │                                   │<── list_models_result (con caché TTL 5min) ──│
  │<── {models: [...]} ───────────────│                        │                    │
  │                                   │                        │                    │
  │── PATCH /chat/conversations/{id} >│                        │                    │
  │   Body: {model_id: "llama-3"}     │                        │                    │
  │                                   │── list_models (caché) ──────────────────────>│
  │                                   │── set_conversation_model ──>│               │
  │<── {status, model_id} ────────────│                        │                    │
```

---

## Endpoints de Sistema

### `GET /`

**Descripción:** Endpoint raíz de comprobación de vida (liveness, no readiness).  
**Autenticación:** Ninguna.

**Respuesta `200 OK`:**
```json
{
  "message": "Welcome to JotaOrchestrator",
  "environment": "development",
  "status": "online"
}
```

---

### `GET /health`

**Descripción:** Health Check profundo. Comprueba la conectividad con JotaDB y el InferenceEngine. Útil para balanceadores de carga y monitorización.  
**Autenticación:** Ninguna.

**Respuesta `200 OK` (todos los componentes sanos):**
```json
{
  "status": "ok",
  "components": {
    "inference_engine": "connected",
    "jota_db": "connected"
  }
}
```

**Respuesta `503 Service Unavailable` (algún componente caído):**
```json
{
  "status": "degraded",
  "components": {
    "inference_engine": "disconnected",
    "jota_db": "connected"
  }
}
```

> **Nota:** El estado del `inference_engine` refleja si el WebSocket persistente interno está en `OPEN`. No implica que el motor esté disponible para inferencia (puede estar cargando un modelo).

---

## Endpoints de Modelos

### `GET /chat/models` *(nuevo)*

**Descripción:** Devuelve la lista de modelos AI disponibles en el InferenceCenter. La respuesta se cachea en memoria durante **5 minutos** para evitar sobrecargar el bus de mensajes WebSocket interno.  
**Autenticación:** `x-client-key` requerido.

**Headers:**
| Header | Tipo | Requerido | Descripción |
|--------|------|-----------|-------------|
| `x-client-key` | string | ✅ | Clave de autenticación del cliente |

**Respuesta `200 OK`:**
```json
{
  "status": "success",
  "models": [
    {
      "id": "llama-3-8b-instruct",
      "name": "Llama 3 8B Instruct",
      "size": "8B",
      "format": "gguf"
    },
    {
      "id": "mistral-7b-v0.3",
      "name": "Mistral 7B v0.3",
      "size": "7B",
      "format": "gguf"
    }
  ]
}
```

> El esquema exacto de cada objeto modelo depende del InferenceEngine. El Orchestrator lo retransmite tal cual.

**Errores:**
| Código | Causa |
|--------|-------|
| `401` | `x-client-key` ausente o inválido |
| `503` | InferenceEngine no disponible o timeout (10s) |

---

## Endpoints de Conversaciones

### `GET /chat/conversations/{user_id}`

**Descripción:** Lista las últimas N conversaciones del usuario. Los resultados están filtrados por `client_id`, por lo que un cliente no puede ver las conversaciones de otro.  
**Autenticación:** `x-client-key` requerido.

**Parámetros de ruta:**
| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `user_id` | string | Identificador del usuario |

**Query params:**
| Parámetro | Tipo | Default | Rango | Descripción |
|-----------|------|---------|-------|-------------|
| `limit` | int | `10` | 1–100 | Número de conversaciones a retornar |

**Headers:**
| Header | Tipo | Requerido |
|--------|------|-----------|
| `x-client-key` | string | ✅ |

**Respuesta `200 OK`:**
```json
{
  "status": "success",
  "conversations": [
    {
      "id": "conv-uuid-1234",
      "user_id": "usuario1",
      "model_id": "llama-3-8b-instruct",
      "created_at": "2026-03-03T17:00:00Z",
      "updated_at": "2026-03-03T17:45:00Z"
    }
  ]
}
```

**Errores:**
```json
{ "status": "error", "message": "Unauthorized" }
{ "status": "error", "message": "<detalle del error>" }
```

---

### `GET /chat/conversations/{user_id}/{conversation_id}/messages`

**Descripción:** Devuelve el historial de mensajes de una conversación específica, ordenados cronológicamente. Filtrado por `client_id`.  
**Autenticación:** `x-client-key` requerido.

**Parámetros de ruta:**
| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `user_id` | string | Identificador del usuario |
| `conversation_id` | string | UUID de la conversación |

**Query params:**
| Parámetro | Tipo | Default | Rango | Descripción |
|-----------|------|---------|-------|-------------|
| `limit` | int | `50` | 1–1000 | Número de mensajes a retornar |

**Headers:**
| Header | Tipo | Requerido |
|--------|------|-----------|
| `x-client-key` | string | ✅ |

**Respuesta `200 OK`:**
```json
{
  "status": "success",
  "messages": [
    {
      "id": "msg-uuid-0001",
      "conversation_id": "conv-uuid-1234",
      "role": "user",
      "content": "Busca información sobre energía solar",
      "created_at": "2026-03-03T17:00:10Z",
      "metadata": null
    },
    {
      "id": "msg-uuid-0002",
      "conversation_id": "conv-uuid-1234",
      "role": "assistant",
      "content": "Voy a buscar información actualizada...",
      "created_at": "2026-03-03T17:00:12Z",
      "metadata": {
        "model_id": "llama-3-8b-instruct",
        "thinking": true
      }
    },
    {
      "id": "msg-uuid-0003",
      "conversation_id": "conv-uuid-1234",
      "role": "tool",
      "content": "{\"results\": [{\"title\": \"Solar energy overview...\"}]}",
      "created_at": "2026-03-03T17:00:14Z",
      "metadata": {
        "tool_name": "web_search",
        "execution_time": "1.45s"
      }
    },
    {
      "id": "msg-uuid-0004",
      "conversation_id": "conv-uuid-1234",
      "role": "assistant",
      "content": "La energía solar es una fuente de energía renovable...",
      "created_at": "2026-03-03T17:00:18Z",
      "metadata": {
        "model_id": "llama-3-8b-instruct"
      }
    }
  ]
}
```

> **Roles de mensaje:**
> - `user` — Mensaje del usuario.
> - `assistant` — Respuesta del modelo. `metadata.thinking=true` indica pensamiento pre-herramienta (no visible al usuario en tiempo real).
> - `tool` — Resultado de una herramienta ejecutada. `metadata.tool_name` y `metadata.execution_time` proporcionan trazabilidad.
> - `system` — Mensajes de sistema internos.

**Errores:**
```json
{ "status": "error", "message": "Unauthorized" }
{ "status": "error", "message": "<detalle del error>" }
```

---

### `PATCH /chat/conversations/{conversation_id}` *(nuevo)*

**Descripción:** Actualiza el modelo AI asignado a una conversación. Antes de persistir, el Orchestrator valida que el `model_id` exista en el InferenceEngine (usando la caché de `GET /chat/models`). Si el Engine no responde, persiste el cambio de todos modos (degraded mode).  
**Autenticación:** `x-client-key` requerido.

**Parámetros de ruta:**
| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `conversation_id` | string | UUID de la conversación a modificar |

**Headers:**
| Header | Tipo | Requerido |
|--------|------|-----------|
| `x-client-key` | string | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Cuerpo de la petición:**
```json
{
  "model_id": "mistral-7b-v0.3"
}
```

**Respuesta `200 OK`:**
```json
{
  "status": "success",
  "conversation_id": "conv-uuid-1234",
  "model_id": "mistral-7b-v0.3"
}
```

**Errores:**
| Código | Causa |
|--------|-------|
| `401` | `x-client-key` ausente o inválido |
| `404` | `model_id` no encontrado en el Engine. La respuesta incluye la lista de modelos disponibles. |
| `500` | Fallo al persistir en JotaDB |

```json
// Ejemplo 404
{
  "detail": "Model 'gpt-9000' not found in Engine. Available: ['llama-3-8b-instruct', 'mistral-7b-v0.3']"
}
```

---

## Endpoints de Chat

### `POST /chat`

**Descripción:** Endpoint REST síncrono para clientes que no soporten WebSockets. Recibe un mensaje de texto, ejecuta la inferencia completa internamente y devuelve la respuesta final concatenada (sin streaming). Cada llamada crea una nueva conversación.  
**Autenticación:** `x-client-key` requerido.

**Headers:**
| Header | Tipo | Requerido |
|--------|------|-----------|
| `x-client-key` | string | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Cuerpo de la petición:**
```json
{
  "text": "¿Cuál es la capital de Francia?",
  "user_id": "usuario1",
  "model_id": "llama-3-8b-instruct"
}
```

| Campo | Tipo | Requerido | Default | Descripción |
|-------|------|-----------|---------|-------------|
| `text` | string | ✅ | — | Mensaje del usuario |
| `user_id` | string | ❌ | `"api_user"` | Identificador del usuario |
| `model_id` | string | ❌ | `null` | Modelo a usar (si `null`, usa el modelo cargado en el Engine) |

**Flujo interno:**
1. Autenticación con `client_key`.
2. Creación de nueva conversación en JotaDB.
3. Apertura de sesión efímera en el InferenceEngine (cierra la anterior si existía para ese `user_id`).
4. Inyección de contexto de la conversación en la sesión.
5. Guardado del mensaje del usuario en JotaDB.
6. Streaming interno de tokens → acumulación en buffer.
7. Guardado de la respuesta del asistente en JotaDB (con `metadata.model_id`).
8. Liberación de la sesión de inferencia.
9. Devolución de la respuesta completa.

**Respuesta `200 OK`:**
```json
{
  "status": "success",
  "response": "La capital de Francia es París."
}
```

**Errores:**
```json
{ "status": "error", "message": "Unauthorized" }
{ "status": "error", "message": "Inference timed out waiting for token" }
{ "status": "error", "message": "<detalle del error>" }
```

> ⚠️ **Limitación:** Este endpoint no soporta conversaciones multi-turno entre llamadas distintas, ya que siempre crea una conversación nueva. Para conversaciones continuas, usa el WebSocket.

---

### `WebSocket /ws/chat/{user_id}`

**Descripción:** Conexión WebSocket persistente para chat en tiempo real con streaming de tokens. Soporta conversaciones multi-turno en una sola conexión.  
**Autenticación:** Via header o query param (ver abajo).

#### Conexión y Autenticación

```
ws://host:port/ws/chat/{user_id}
  ?conversation_id=conv-uuid-1234   (opcional, retoma conversación existente)
  ?model_id=llama-3-8b-instruct     (opcional, modelo a usar)
  &x_client_key=<tu_clave>          (o via header x-client-key)
```

**Parámetros de ruta:**
| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `user_id` | string | Identificador del usuario |

**Query params:**
| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `conversation_id` | string | ❌ | UUID de conversación a retomar. Si se omite, se crea una nueva. |
| `model_id` | string | ❌ | Modelo AI para esta sesión. Si se omite, usa el cargado actualmente en el Engine. |
| `x_client_key` | string | ✅* | Clave de autenticación (alternativa al header) |
| `client_key` | string | ✅* | Alias alternativo para `x_client_key` |

> \* Al menos uno de `x-client-key` (header) o `x_client_key`/`client_key` (query) es obligatorio.

**Si la autenticación falla:** El servidor cierra el WebSocket con código `4001` (Unauthorized) antes de hacer accept. No se envía ningún frame.

#### Ciclo de vida de la conexión

```
APERTURA
  ├─ Validación de client_key                → close(4001) si falla
  ├─ Gestión de conversación                 → create_conversation() si no hay conversation_id
  ├─ ensure_session()                        → cierra sesión previa del user_id si existía
  ├─ get_conversation_messages() + set_context() → inyecta historial previo al Engine
  └─ websocket.accept()                      → conexión lista

BUCLE DE MENSAJES (mientras el cliente esté conectado)
  ├─ Recibir texto del cliente
  ├─ save_message(role="user")
  └─ LOOP streaming:
      ├─ infer(...) → yield tokens
      └─ send_text(token) por cada token recibido

CIERRE (WebSocketDisconnect o error)
  └─ release_session(user_id)               → libera sesión en InferenceEngine
```

#### Protocolo de mensajes

| Dirección | Formato | Descripción |
|-----------|---------|-------------|
| Cliente → Servidor | Texto plano | El mensaje del usuario. Ej: `"¿Cuándo fue la Revolución Francesa?"` |
| Servidor → Cliente | JSON `{"type": "token", "content": "..."}` | Fragmentos de texto de la respuesta del modelo |
| Servidor → Cliente | JSON `{"type": "status", "content": "..."}` | Indicadores de estado (búsqueda, procesamiento) — **no es texto para el usuario** |
| Servidor → Cliente | JSON `{"type": "model_switched", ...}` | Confirmación de cambio de modelo mid-session |
| Servidor → Cliente | JSON `{"type": "error", ...}` | Mensaje de error |
| Cierre con `4001` | — | Autenticación fallida (antes de `accept`) |
| Cierre con `1011` | — | Error interno del servidor |

> **Importante:** El cliente debe parsear cada frame como JSON y actuar según el campo `type`:
> - `token` → Acumular `content` en el buffer de respuesta visible.
> - `status` → Mostrar indicador visual (spinner, texto de estado) sin acumular en la respuesta.

#### Ejemplo de cliente JavaScript

```javascript
const ws = new WebSocket(
  `ws://localhost:8000/ws/chat/usuario1` +
  `?conversation_id=conv-uuid-1234` +
  `&x_client_key=mi_clave_secreta`
);

let buffer = "";

ws.onmessage = (event) => {
  try {
    const msg = JSON.parse(event.data);
    
    if (msg.type === "token") {
      // Texto de respuesta del modelo — acumular y mostrar
      buffer += msg.content;
      document.getElementById("response").textContent = buffer;
    } else if (msg.type === "status") {
      // Indicador de estado — mostrar spinner o texto temporal
      document.getElementById("status").textContent = msg.content;
    } else if (msg.type === "error") {
      console.error("Server error:", msg.message);
    } else if (msg.type === "model_switched") {
      console.log("Model changed to:", msg.model_id);
    }
  } catch (e) {
    // Fallback: tratar como texto plano
    buffer += event.data;
  }
};

ws.onopen = () => {
  buffer = "";
  ws.send("Busca información sobre inteligencia artificial");
};

ws.onerror = (error) => console.error("WebSocket error:", error);

ws.onclose = (event) => {
  console.log(`Conexión cerrada: código ${event.code}, razón: ${event.reason}`);
};
```

#### Gestión de contexto y memoria

- Al abrirse la conexión, el Orchestrator **recupera automáticamente** el historial de la `conversation_id` desde JotaDB e inyecta los mensajes como contexto en la sesión del InferenceEngine via `set_context`.
- Cada mensaje de usuario y cada respuesta del asistente son **persistidos automáticamente** en JotaDB durante la sesión.
- Las respuestas del asistente guardadas incluyen `metadata.model_id` para trazabilidad del modelo usado.
- Si una inferencia se interrumpe (desconexión abrupta), la respuesta parcial se guarda con el sufijo `[INTERRUPTED]`.

---

## Códigos de Error y Respuestas de Error

### HTTP

| Código | Causa típica |
|--------|-------------|
| `401 Unauthorized` | `x-client-key` ausente, expirado, o inválido |
| `404 Not Found` | `model_id` no existe en el Engine |
| `500 Internal Server Error` | Fallo al persistir en JotaDB |
| `503 Service Unavailable` | InferenceEngine no disponible o timeout |

### WebSocket (códigos de cierre)

| Código | Significado |
|--------|-------------|
| `4001` | Autenticación rechazada (client_key inválido o ausente) |
| `1011` | Error interno del servidor durante la sesión |
| `1000` | Cierre normal iniciado por el cliente |

---

## Notas de Implementación y Limitaciones

### Caché de modelos
`GET /chat/models` y la validación en `PATCH /chat/conversations/{id}` usan una **caché en memoria con TTL de 5 minutos**. Esto significa que:
- Los modelos recién añadidos al Engine pueden tardar hasta 5 minutos en aparecer.
- Reinicios del Orchestrator invalidan la caché (se recarga en la próxima llamada).

### Sesiones de inferencia por usuario
El InferenceEngine mantiene **una sesión activa por `user_id`** a la vez. Si:
- Se abre una nueva conexión WebSocket para un `user_id` que ya tiene sesión → la anterior se cierra automáticamente.
- Se hace `POST /chat` para un `user_id` con sesión WebSocket activa → la sesión WebSocket se interrumpe.

### Aislamiento de datos
Las conversaciones y mensajes están asociados al `client_id` (derivado de la `client_key`). Un cliente no puede acceder a datos de otro cliente, incluso si conoce el `user_id` o `conversation_id`.

### Gestión del modelo en el Engine
El `model_id` en `POST /chat` y en la apertura del WebSocket indica al Orchestrator **qué modelo debe estar cargado** en el InferenceEngine. El Orchestrator puede enviar un comando `COMMAND_LOAD_MODEL` al Engine si el modelo no está cargado actualmente. La carga puede fallar si:
- Hay una inferencia en progreso (`InferenceEngineBusyError` → `503`).
- El modelo no existe en el Engine (`ModelNotFoundError` → `404`).

### Transcripción de audio
El servicio de transcripción vía MQTT está **deshabilitado** en la versión actual. Se habilitará en una release futura cuando la integración MQTT esté lista.

### Prefijo de versión de API
Actualmente los endpoints están en la raíz (`/chat/...`). Está previsto migrar a `/api/v1/chat/...` en futuras versiones. La línea correspondiente en `main.py` está comentada para facilitar la transición.
