"""
inference.py (Paquete modularizado)
~~~~~~~~~~~~
Cliente WebSocket persistente para comunicarse con el InferenceCenter.
Este paquete expone las mismas clases que el módulo original para 
mantener la compatibilidad estricta.
"""

from .client import InferenceClient
from .exceptions import InferenceEngineBusyError, ModelNotFoundError

__all__ = ["InferenceClient", "InferenceEngineBusyError", "ModelNotFoundError"]
