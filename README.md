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
- Soporte **Multusesión**: Gestiona múltiples conversaciones simultáneamente sobre un solo canal.
- **Protocolo Seguro**: Autenticación inmediata (`client_id`, `api_key`) y re-conexión automática.

## 🛠️ Configuración y Ejecución

1. **Variables de Entorno**:
   Crea un archivo `.env` basado en `.env.example`:
   ```env
   INFERENCE_SERVICE_URL="ws://greenhouse.local:3000/api/inference"
   INFERENCE_CLIENT_ID="tu_id"
   INFERENCE_API_KEY="tu_key"
   ```

2. **Ejecutar Orquestador**:
   ```bash
   uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
   ```

3. **Endpoints Principales**:
   - `GET /health`: Estado del servicio.
   - `WS /api/v1/ws/chat/{user_id}`: Chat en vivo.

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
