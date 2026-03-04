# Visión Técnica: Jota - El Cerebro Centralizado

Este documento define la arquitectura, los estándares y la hoja de ruta para **Jota**, un ecosistema de asistente virtual diseñado para la persistencia, la conciencia contextual y la eficiencia.

---

## 1. Resumen de Infraestructura

Jota funciona como una **arquitectura backend distribuida** orquestada centralmente.

### Módulos Núcleo (Core)
* **Jota-Orchestrator (Python/FastAPI):** El centro nervioso. Actúa como un **Enrutador Cognitivo** que gestiona la lógica de negocio, la memoria y la orquestación.
    - **Estado Actual**: Integrado con Inference Center (WebSocket) y lógica de sesiones asíncrona.
* **Inference Center (C++):** Motor de inferencia remoto.
* **Transcription API (C++):** Servidor de streaming STT.

---

## 2. Arquitectura de Orquestación

### Flujo de Inferencia End-to-End (Implementado)
El orquestador actúa como un proxy inteligente y gestor de estado:

1. **Entrada de Usuario**: Recibida vía WebSocket (`/ws/chat/{user_id}`) o REST.
2. **Controlador (`JotaController`)**:
   - Recupera el historial de **Memoria**.
   - Invoca al cliente de inferencia.
3. **Cliente de Inferencia (`InferenceClient`)**:
   - Gestiona la conexión WebSocket persistente con el motor C++.
   - **Stateless**: Delega el estado de la sesión en `MemoryManager` (JotaDB).
   - Autentica (`auth`), crea sesiones (`create_session`) y las cierra explícitamente (`close_session`) bajo demanda para no saturar los límites de recursos.
   - Despacha streams de tokens concurrentes usando colas asíncronas (`asyncio.Queue`).
   - Soporta **Exponential Backoff** para reconexión automática.
   - **Detección de `<tool_call>`**: Intercepta tokens que contienen etiquetas XML de tool calling, parsea el JSON y emite un dict estructurado al controlador.
   - **Gramáticas GBNF**: Genera y envía gramáticas dinámicas al motor para forzar salidas JSON cuando hay herramientas registradas.
4. **Streaming**: Los tokens fluyen en tiempo real de `InferenceCenter` -> `Orchestrator` -> `User` sin bloqueo.
5. **Tool Execution Loop**: Si el modelo emite un `<tool_call>`, el controlador pausa el streaming, ejecuta la herramienta (Tavily, MCP, etc.), guarda el resultado en JotaDB, y relanza una segunda inferencia con el contexto actualizado.

### Gestión de Memoria Unificada (JotaDB)
* **Persistencia Externa:** El orquestador no almacena estado. Todo reside en JotaDB.
* **Contexto de Sesión:** Mapeo dinámico `conversación_id` <-> `inference_session_id` gestionado por JotaDB.
* **Deep Health Check:** Monitoreo activo de conexiones a JotaDB y Motor de Inferencia (`/health`).

---

## 3. Plan de Implementación

### Fase 1: El Puente de Datos (✅ Completado)
* [x] Configurar `InferenceClient` con protocolo asíncrono y autenticación.
* [x] Implementar streaming de tokens en tiempo real (Async Generators).
* [x] API WebSocket para clientes finales.

### Fase 2: Lógica de Decisión y Tool Calling (✅ Completado)
* [x] Implementar `ToolManager` con decorador `@tool` y generación automática de esquemas JSON.
* [x] Integrar Tavily Web Search como herramienta asíncrona.
* [x] Integrar cliente MCP (Model Context Protocol) para herramientas externas.
* [x] Implementar bucle de re-inferencia recursivo (modelo → herramienta → re-inferencia).
* [x] Generar gramáticas GBNF dinámicas para output estructurado.
* [x] Tokens de estado (`{"type": "status"}`) por WebSocket para indicadores de progreso.
* [x] Filtrado de "pensamientos" pre-herramienta (guardados en DB, ocultos al usuario).

### Fase 2.5: Seguridad y Sandboxing de Herramientas (✅ Completado)
* [x] Sistema de permisos por rol (`public` / `user` / `admin`) integrado con `client_id`.
* [x] Truncado de salida de herramientas (4000 chars) para prevención de Context Overflow.
* [x] Filtrado dinámico: el modelo solo ve herramientas accesibles al cliente actual.

### Fase 3: Interfaz y Observabilidad
* Web Dashboard para control y métricas.

---

## 4. Estándares
* **WebSockets (WS/WSS):** Estándar comunicación streaming.
* **AsyncIO:** Núcleo de concurrencia en Python para manejar I/O intenso sin bloquear.
* **Seguridad:** Autenticación por Tokens en capa de transporte + permisos por rol en herramientas.
* **GBNF Grammars:** Gramáticas formales para constraining de salidas del modelo.