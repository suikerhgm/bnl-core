"""
Orquestador de conversación del bot NexusAgentes.
Contiene la lógica de conversación principal (process_message).
Integra recuperación de memoria contextual antes de llamar a la IA.
"""
from typing import Dict

from core.execution_engine import ExecutionEngine


async def process_message(user_message: str, chat_id: int, state: Dict) -> str:
    """
    Procesa un mensaje del usuario con el learning loop completo.
    Delega toda la lógica al ExecutionEngine.
    """
    engine = ExecutionEngine()
    return await engine.run(user_message, str(chat_id), state)
