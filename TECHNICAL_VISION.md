# Visión Técnica: Jota - El Cerebro Centralizado

Este documento define la arquitectura, los estándares y la hoja de ruta para **Jota**, un ecosistema de asistente virtual diseñado para la persistencia, la conciencia contextual y la eficiencia en hardware limitado.

---

## 1. Resumen de Infraestructura

Jota se aleja del concepto de cliente físico dedicado para convertirse en una **arquitectura backend distribuida**. El sistema está optimizado para funcionar sobre una **GTX 1060 (4GB VRAM)** mediante una estrategia de **Atención Selectiva**.

### Módulos Núcleo (Core)
* **Jota-Orchestrator (Python/FastAPI):** El centro nervioso. Actúa como un **Enrutador Cognitivo** que gestiona la lógica de negocio, la memoria y la orquestación de otros módulos.
* **Inference Center (C++):** Motor de inferencia de alto rendimiento basado en `llama.cpp`. Solo se activa para tareas de razonamiento profundo o generación compleja para optimizar la VRAM.
* **Transcription API (C++):** Servidor de streaming STT (Speech-to-Text) diseñado para recibir audio continuo y devolver texto en tiempo real con seguridad SSL/WSS.

---

## 2. Especificación del Orchestrator: El Enrutador Cognitivo

El Orchestrator no es un simple pasarela; es el encargado de decidir el "nivel de esfuerzo" necesario para cada petición.

### Clasificación de Intenciones Multidimensional
Para maximizar los recursos, el Orchestrator clasifica cada entrada en una de estas categorías:

| Categoría | Descripción | Ejecución |
| :--- | :--- | :--- |
| **ACTION_IMMEDIATE** | Comandos directos de domótica (luces, temperatura). | Scripts Python / Matter Center API. |
| **SYSTEM_QUERY** | Consultas sobre el estado de Jota o telemetría del servidor. | Acceso directo a métricas internas. |
| **SIMPLE_FACT** | Preguntas con respuesta directa o cálculos matemáticos. | Modelo local 1B/2B o funciones de código. |
| **RESEARCH_SEARCH** | Necesidad de información externa y actualizada. | Herramientas de búsqueda (Future MCP Tools). |
| **COMPLEX_REASONING** | Programación, análisis ético o reflexión profunda. | **Inference Center (C++)**. |

### Gestión de Memoria Unificada
* **Memoria de Trabajo (Redis):** Mantiene el historial de la conversación actual para proporcionar coherencia inmediata.
* **Memoria Semántica (Vector DB):** Almacenamiento de largo plazo para que Jota "aprenda" preferencias y datos del hogar.
* **Contexto de Inyección:** El Orchestrator reconstruye el prompt para el Inference Center añadiendo los datos relevantes de la sesión antes de cada llamada.

---

## 3. Plan de Implementación: Fase de Estabilización

### Paso 1: El Puente de Datos
* Configurar el Orchestrator para recibir y procesar el flujo de texto de la `Transcription_API`.
* Implementar el cliente asíncrono en Python para comunicarse con el servidor de inferencia de C++ utilizando el protocolo de Opcodes (`infer`, `token`, `end`).

### Paso 2: Lógica de Decisión y Routing
* Desarrollar el `IntentRouter` con soporte para modelos de lenguaje ligeros que funcionen en CPU.
* Crear la estructura de "Tool Calling" para ejecutar acciones de domótica sin despertar el motor pesado de la GPU.

### Paso 3: Interfaz de Control (Web Dashboard)
* Desarrollar una aplicación web centralizada que sirva como chat y panel de control.
* Visualización en tiempo real de las métricas de inferencia (TTFT, TPS) capturadas por el motor de C++.

---

## 4. Estándares y Mejores Prácticas

### Comunicación y Protocolos
* **WebSockets (WS/WSS):** Estándar para el streaming de audio e intercambio de tokens en tiempo real.
* **JSON Estructurado:** Todas las comunicaciones entre el Orchestrator y los nodos deben seguir el esquema definido en `Protocol.h` para garantizar la compatibilidad.

### Ingeniería de Software
* **Agnosticismo de Hardware:** El backend debe exponer APIs que permitan conectar desde un PC hasta un microcontrolador ESP32 mediante interfaces simplificadas.
* **Eficiencia C++:** Los módulos críticos (Inferencia/STT) deben mantener el uso de RAII y punteros inteligentes para garantizar estabilidad a largo plazo.