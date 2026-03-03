# Documentación de Endpoints del Cliente

A continuación se detalla exhaustivamente cada uno de los endpoints expuestos por JotaOrchestrator para el consumo de los clientes, tanto por HTTP/REST como por WebSocket.

---

## Endpoints de Sistema (Generales)

### 1. `GET /`
**Propósito:** Endpoint raíz para comprobar que la API principal está en pie.
**Respuesta exitosa (200 OK):**
```json
{
  "message": "Welcome to JotaOrchestrator",
  "environment": "development|production",
  "status": "online"
}
```
**Autenticación:** Ninguna.

### 2. `GET /health`
**Propósito:** Deep Health Check. Verifica la conectividad con los servicios subyacentes, como JotaDB y el Inference Engine. Útil para balanceadores de carga o monitorizaciones.
**Respuesta exitosa (200 OK):**
```json
{
  "status": "ok",
  "components": {
    "inference_engine": "connected",
    "jota_db": "connected"
  }
}
```
**Respuesta degradada (503 Service Unavailable):** Si alguno de los componentes está fallando (`disconnected`).
**Autenticación:** Ninguna.

---

## Endpoints de Chat y Conversaciones

### 3. `GET /chat/conversations/{user_id}`
**Propósito:** Obtiene un listado de las últimas conversaciones de un usuario específico.
**Parámetros de Ruta:**
- `user_id` (string): El identificador del usuario.
**Parámetros de Query:**
- `limit` (int, opcional): Número de conversaciones a recuperar (por defecto 10, mínimo 1, máximo 100).
**Headers Requeridos:**
- `x-client-key` (string): Clave de autenticación del cliente.
**Respuestas:**
- Exitoso: `{"status": "success", "conversations": [...]}`
- Error / No Autorizado: `{"status": "error", "message": "..."}`

### 4. `GET /chat/conversations/{user_id}/{conversation_id}/messages`
**Propósito:** Obtener los mensajes de una conversación específica.
**Parámetros de Ruta:**
- `user_id` (string): Identificador del usuario.
- `conversation_id` (string): Identificador de la conversación.
**Parámetros de Query:**
- `limit` (int, opcional): Número de mensajes a recuperar (por defecto 50, máximo 1000).
**Headers Requeridos:**
- `x-client-key` (string): Clave de autenticación del cliente.
**Respuestas:**
- Exitoso: `{"status": "success", "messages": [...]}`
- Error / No Autorizado: `{"status": "error", "message": "..."}`

### 5. `POST /chat`
**Propósito:** Recibe texto directamente a través de REST e inicia (o continúa) una conversación procesada por el orquestador. Devuelve la respuesta generada completamente mediante un string (sin websockets).
**Cuerpo de la Petición (JSON):**
```json
{
  "text": "mensaje enviado por el usuario",
  "user_id": "api_user" // (opcional, valor por defecto: "api_user")
}
```
**Headers Requeridos:**
- `x-client-key` (string): Clave de autenticación del cliente.
**Respuestas:**
- Exitoso: `{"status": "success", "response": "texto de respuesta completo"}`
- Error / No Autorizado: `{"status": "error", "message": "..."}`
*Nota:* Este endpoint es mantenido por compatibilidad con clientes exclusivamente REST. Cada petición aparta una sesión de inferencia de corta duración y devuelve la respuesta final concatenada.

### 6. `WebSocket /ws/chat/{user_id}`
**Propósito:** Comunicación de chat en tiempo real bidireccional (streaming de respuesta).
**Parámetros de Ruta:**
- `user_id` (string): Identificador del usuario que se conecta.
**Parámetros de Query:**
- `conversation_id` (string, opcional): ID de conversación si se quiere retomar una anterior. Si no se envía un `conversation_id`, se creará uno nuevo al conectar.
- `x_client_key` o `client_key` (string): Se permite pasar el token de autenticación por url para facilitar a clientes web.
**Headers Opcionales (alternativa a Query):**
- `x-client-key` (string)
**Flujo:**
1. Abertura del socket (autenticación y preparativos de sesión).
2. El cliente envía mensajes de texto sueltos por el WebSocket.
3. El servidor devuelve pedazos de la respuesta inferida como streams de texto por el mismo socket.
4. El cierre desconecta la sesión de inferencia en segundo plano.

---

## ⚠️ Análisis de Redundancias y Mejoras

He detectado las siguientes anomalías u oportunidades de limpieza en el código:

1. **Endpoint Duplicado en `chat.py`**:
   Existen dos funciones que declaran y manejan exactamente la misma ruta `GET /chat/conversations/{user_id}/{conversation_id}/messages`:
   - En la línea 31: `get_conversation_messages` (límite máximo 1000).
   - En la línea 53: `get_conversation_messages_endpoint` (límite máximo 100).
   *Resolución:* He procedido a eliminar la segunda función duplicada en el archivo `chat.py` para limpiar el código.

2. **Endpoints Prefix y Modularidad**:
   En `main.py`, la línea `# app.include_router(chat_router, prefix="/api/v1")` está comentada y, en cambio, se usa `app.include_router(chat_router)`. Esto hace que los endpoints queden todos en el formato global (e.g., `/chat...`). Sería recomendable estandarizar a un prefijo `/api/v1` para futuras versiones.
