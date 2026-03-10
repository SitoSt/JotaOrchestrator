"""
exceptions.py
~~~~~~~~~~~~~
Excepciones personalizadas para el cliente de inferencia.
"""

class InferenceEngineBusyError(Exception):
    """El Engine rechazó el comando porque hay una inferencia en progreso."""

class ModelNotFoundError(Exception):
    """El Engine no encontró el modelo solicitada."""
