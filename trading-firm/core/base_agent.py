"""
Classe de base pour tous les agents de la firme.

Chaque "employé" (agent) :
  - a un nom et un rôle
  - s'abonne à certains topics du bus de messages
  - a un cycle de vie start/stop propre
  - log ses décisions pour l'audit
"""

from abc import ABC, abstractmethod
import logging

from core.message_bus import MessageBus


class BaseAgent(ABC):
    def __init__(self, name: str, bus: MessageBus) -> None:
        self.name = name
        self.bus = bus
        self.logger = logging.getLogger(name)
        self._running = False

    @abstractmethod
    async def setup(self) -> None:
        """Enregistrer les abonnements aux topics du bus. Appelé une fois au démarrage."""
        raise NotImplementedError

    async def start(self) -> None:
        await self.setup()
        self._running = True
        self.logger.info(f"{self.name} démarré et opérationnel.")

    async def stop(self) -> None:
        self._running = False
        self.logger.info(f"{self.name} arrêté.")

    async def emit(self, topic: str, payload: dict) -> None:
        await self.bus.publish(topic, payload, source=self.name)
