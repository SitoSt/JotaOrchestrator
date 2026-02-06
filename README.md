# Jota: Ecosistema de Asistente Virtual Persistente

Jota es un ecosistema de asistencia inteligente diseñado para ofrecer una memoria unificada y lógica centralizada en todo el hogar. A diferencia de los asistentes comerciales, Jota prioriza el procesamiento local, la soberanía de datos y la extensibilidad mediante una arquitectura de microservicios de alto rendimiento.

## 🧠 El Concepto: "Cerebro Agnóstico"
Tras pivotar el desarrollo, Jota se centra en un núcleo de backend robusto (Orchestrator e Inference Core) que puede recibir datos de cualquier interfaz (App móvil, escritorio, o futuros nodos Edge). 

## 🏗️ Estructura del Proyecto
El sistema se divide en módulos especializados:

* **Orchestrator (En Desarrollo):** El centro de mando en Python/FastAPI que gestiona el contexto, la memoria y el enrutamiento de tareas.
* **Inference Center (C++):** Motor de inferencia de alto rendimiento basado en `llama.cpp` para la ejecución de LLMs.
* **Transcription API (C++):** Servidor de streaming para transcripción de audio en tiempo real basado en Whisper.
* **JotaClient (C++):** Cliente ligero para captura de audio y telemetría local (Actualmente en pausa técnica).

## 🚀 Objetivo Inmediato
Consolidar el flujo **Audio -> Texto -> Intención -> Acción** de forma totalmente desacoplada del hardware final.
