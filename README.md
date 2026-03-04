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
- **WebSocket:** `/ws/chat/{user_id}` para comunicación bidireccional y streaming de tokens.
- **REST:** `POST /chat` para compatibilidad (request/response).

### 2. Integración de Inferencia
- Cliente asíncrono robusto conectado al **Inference Center**.
- Soporte **Multisesión Stateless**: Gestiona múltiples conversaciones simultáneamente delegando el estado en JotaDB.
- **Resiliencia**: Autenticación inmediata, **Exponential Backoff** para reconexión, y aborto de sesiones en desconexión del cliente.

### 3. Sistema de Herramientas (Tool System)
- **ToolManager** con decorador `@tool` para registro dinámico, generación automática de esquemas JSON y permisos por rol.
- **Registro automático en startup**: `src/tools/__init__.py` importa todos los módulos de tools al arrancar, garantizando que el decorador `@tool` se ejecute.
- **Tavily Web Search**: Búsqueda web asíncrona integrada vía `tavily-python`.
- **MCP Client**: Integración con servidores MCP (Model Context Protocol) para herramientas externas.
- **System Prompt dinámico**: El modelo recibe instrucciones de tool calling vía system prompt estructurado. Incluye lista de herramientas disponibles, formato exacto del `<tool_call>`, ejemplos con herramientas reales y reglas de uso.
- **Detección dual de tool calls**:
  - **Primaria** (streaming parser en `inference.py`): intercepta `<tool_call>` a nivel de token mientras el modelo genera, emitiendo un dict estructurado al controlador.
  - **Fallback** (text parser en `controller.py`): acumula tokens y usa `extract_tool_calls()` para detectar bloques que el parser de streaming pudiera haber partido entre chunks.
- **Bucle de Re-Inferencia**: El modelo pausa su respuesta, la herramienta se ejecuta, el resultado se guarda en JotaDB, y se relanza una segunda inferencia con el contexto completo.
- ~~Gramáticas GBNF~~ *(deprecated)* — Reemplazado por system prompt. Disponible como escape hatch con `params["force_grammar"] = True`.

### 4. Seguridad y Permisos de Herramientas
- **Roles por cliente**: `public` / `user` / `admin` — cada herramienta declara su nivel de acceso requerido.
- **Filtrado dinámico**: El model solo ve las herramientas que el `client_id` tiene permiso de usar.
- **Sandboxing de salida**: Las respuestas de herramientas se truncan automáticamente (`TOOL_MAX_OUTPUT_CHARS`, default 4000 chars) para prevenir desbordamiento de contexto.
- **Cap en historial**: Los resultados de herramientas se capan al inyectarse como contexto (`MEMORY_TOOL_OUTPUT_CAP`, default 1500 chars) para evitar saturación del modelo.

### 5. Memoria y Trazabilidad
- Soporte para rol `tool` en la base de datos con metadata de nombre de herramienta y tiempo de ejecución.
- Los "pensamientos" pre-herramienta del modelo se guardan en DB (`metadata.thinking=true`) pero no se muestran al usuario.
- Tokens de estado estructurados (`{"type": "status"}`) por WebSocket para indicadores de progreso en el frontend.

### 6. Arquitectura de Configuración
- **`src/core/constants.py`**: Constantes de protocolo no configurables vía entorno: tags `<tool_call>` / `</tool_call>`, markers de texto (`[INTERRUPTED]`, `[OUTPUT TRUNCATED]`, etc.). Importadas por todos los módulos que necesitan referenciarlas.
- **`src/core/config.py`**: Settings operacionales sobreescribibles vía `.env` — prompts del agente, timeouts de inferencia, parámetros de Tavily, límites de output, TTLs de caché.
- **`src/utils/tool_parser.py`**: Utilidades de parseo: `extract_tool_calls()`, `validate_tool_call()`, `remove_tool_calls_from_text()`.

## 🛠️ Configuración y Ejecución

### Variables de Entorno

Crea un archivo `.env` basado en `.env.example`. Variables disponibles:

```env
# --- Servicios externos (obligatorias) ---
JOTA_DB_URL="http://localhost:8080"
JOTA_DB_SK="tu_server_key"
INFERENCE_SERVICE_URL="ws://host:3000/api/inference"
ORCHESTRATOR_ID="tu_id"
ORCHESTRATOR_API_KEY="tu_api_key"

# --- Tools (opcional) ---
TAVILY_API_KEY="tu_tavily_key"       # Sin esto, web_search lanza error
TAVILY_SEARCH_DEPTH="basic"          # "basic" | "advanced"
TAVILY_MAX_RESULTS=5

# --- Personalidad del agente (opcional) ---
AGENT_BASE_SYSTEM_PROMPT="You are Jota..."   # Overrides el prompt base
TOOL_FOLLOWUP_PROMPT="The tool has provided..."

# --- Timeouts de inferencia (opcional) ---
INFERENCE_DEFAULT_TEMP=0.7
INFERENCE_TOKEN_TIMEOUT=30.0
INFERENCE_LOAD_MODEL_TIMEOUT=30.0
INFERENCE_LIST_MODELS_TIMEOUT=10.0
INFERENCE_SESSION_TIMEOUT=5.0
MODELS_CACHE_TTL=300.0

# --- Límites de output (opcional) ---
TOOL_MAX_OUTPUT_CHARS=4000
MEMORY_TOOL_OUTPUT_CAP=1500
JOTA_DB_TIMEOUT=10.0

# --- Features (opcional) ---
ENABLE_GBNF_GRAMMAR=false    # Deprecated. true solo para compatibilidad legacy
SSL_VERIFY=true
```

### Ejecutar Orquestador

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### Endpoints Principales
- `GET /health`: **Deep Health Check** (Verifica JotaDB + Motor Inferencia).
- `WS /ws/chat/{user_id}`: Chat en vivo.
- Ver [CLIENT_ENDPOINTS.md](CLIENT_ENDPOINTS.md) para documentación completa.

## 🧪 Testing

El proyecto incluye una suite de pruebas robusta para asegurar la estabilidad del cliente de inferencia (24/7).

### 1. Ejecutar Pruebas Unitarias
```bash
pytest tests/unit/
```

### 2. Ejecutar Pruebas de Integración
```bash
pytest tests/integration/
```

### 3. Ejecutar Pruebas de Carga (Stress Test)
```bash
pytest tests/stress/test_load.py
```

## 🐳 Docker Deployment

```bash
docker compose up --build -d
docker compose logs -f
```

- Usa `python:3.12-slim`.
- **Gunicorn** con **1 worker Uvicorn** (múltiples workers rompen el estado WebSocket compartido entre el Orchestrator y el InferenceEngine).
- `network_mode: "host"` para integración en redes locales.
