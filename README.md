# Jota: Ecosistema de Asistente Virtual Persistente

Jota es un ecosistema de asistencia inteligente diseñado para ofrecer una memoria unificada y lógica centralizada. Prioriza el procesamiento local y la extensibilidad mediante una arquitectura de microservicios.

## 🧠 El Concepto: "Cerebro Agnóstico"
Jota se centra en un núcleo de backend robusto (Orchestrator e Inference Core) que puede recibir datos de cualquier interfaz (App móvil, escritorio, o futuros nodos Edge).

## 🏗️ Estructura del Proyecto
El sistema se divide en módulos especializados:

* **Orchestrator (Python/FastAPI):** El cerebro que gestiona el contexto, sesiones, memoria y conecta con los servicios de inferencia.
* **Inference Center (C++):** Motor de inferencia `llama.cpp` remoto (WebSocket).
* **Transcription API (C++):** Servidor STT para audio en tiempo real.

## 🚀 Características Implementadas

### 1. API de Chat en Tiempo Real
- **WebSocket:** `/api/v1/ws/chat/{user_id}` para comunicación bidireccional y streaming de tokens.
- **REST:** `POST /api/v1/chat` para compatibilidad (request/response).

### 2. Integración de Inferencia
- Cliente asíncrono robusto conectado al **Inference Center**.
- Soporte **Multusesión Stateless**: Gestiona múltiples conversaciones simultáneamente delegando el estado en JotaDB.
- **Resiliencia**: Autenticación inmediata, **Exponential Backoff** para reconexión, y aborto de sesiones en desconexión del cliente.

### 3. Sistema de Herramientas (Tool System)
- **ToolManager** con decorador `@tool` para registro dinámico y generación automática de esquemas JSON.
- **Tavily Web Search**: Búsqueda web asíncrona integrada (top 5 resultados) vía `tavily-python`.
- **MCP Client**: Integración con servidores MCP (Model Context Protocol) vía SDK de Anthropic para herramientas externas.
- **Gramáticas GBNF**: Generación dinámica de gramáticas para forzar salidas JSON estructuradas en el motor de inferencia.
- **Bucle de Re-Inferencia**: El modelo puede pausar su respuesta, ejecutar una herramienta, y reanudar con los datos obtenidos.

### 4. Seguridad y Permisos de Herramientas
- **Roles por cliente**: `public` / `user` / `admin` — cada herramienta declara su nivel de acceso requerido.
- **Sandboxing de salida**: Las respuestas de herramientas se truncan automáticamente (4000 chars) para prevenir desbordamiento de contexto.
- **Filtrado dinámico**: El modelo solo ve las herramientas que el `client_id` tiene permiso de usar.

### 5. Memoria y Trazabilidad
- Soporte para rol `tool` en la base de datos con metadata de nombre de herramienta y tiempo de ejecución.
- Los "pensamientos" pre-herramienta del modelo se guardan en DB (`metadata.thinking=true`) pero no se muestran al usuario.
- Tokens de estado estructurados (`{"type": "status"}`) por WebSocket para indicadores de progreso en el frontend.

## 🛠️ Configuración y Ejecución

1. **Variables de Entorno**:
   Crea un archivo `.env` basado en `.env.example`:
   ```env
   JOTA_DB_URL="http://localhost:8080"
   JOTA_DB_API_KEY="tu_db_key"
   INFERENCE_SERVICE_URL="ws://greenhouse.local:3000/api/inference"
   INFERENCE_CLIENT_ID="tu_id"
   INFERENCE_API_KEY="tu_key"
   TAVILY_API_KEY="tu_tavily_key"  # Opcional: para búsqueda web
   ```

2. **Ejecutar Orquestador**:
   ```bash
   uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
   ```

3. **Endpoints Principales**:
   - `GET /health`: **Deep Health Check** (Verifica JotaDB + Motor Inferencia).
   - `WS /ws/chat/{user_id}`: Chat en vivo.

## 🧪 Testing

El proyecto incluye una suite de pruebas robusta para asegurar la estabilidad del cliente de inferencia (24/7).

### 1. Ejecutar Pruebas Unitarias
Verifica la lógica básica y configuración del cliente.
```bash
pytest tests/unit/
```

### 2. Ejecutar Pruebas de Integración
Levanta un servidor Mock y prueba el flujo completo de autenticación e inferencia.
```bash
pytest tests/integration/
```

### 3. Ejecutar Pruebas de Carga (Stress Test)
Simula múltiples usuarios concurrentes para verificar estabilidad bajo carga.
```bash
pytest tests/stress/test_load.py
```

## 🐳 Docker Deployment

Para un despliegue robusto y fácil de gestionar:

1. **Construir y ejecutar**:
   ```bash
   docker compose up --build -d
   ```
   Esto levantará el servicio en el puerto `8000` con reinicio automático (`unless-stopped`).

2. **Ver logs**:
   ```bash
   docker compose logs -f
   ```

3. **Arquitectura del Contenedor**:
   - Usa `python:3.12-slim`.
   - Implementa **Gunicorn** como gestor de procesos y **Uvicorn** workers para máximo rendimiento y estabilidad.
   - Configurado con `network_mode: "host"` para fácil integración en redes locales.

