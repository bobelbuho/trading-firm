"""
Message Bus - le système nerveux central de la firme.

Chaque agent (analyste, risk manager, exécuteur...) publie et écoute
des messages sur des "topics" (canaux). C'est ce qui permet à des
modules indépendants de collaborer comme une vraie équipe, sans être
directement couplés les uns aux autres.

Exemple de flux :
  MarketDataAgent publie sur "market.tick"
    -> StrategyAgent écoute "market.tick", publie sur "signal.new"
      -> RiskManager écoute "signal.new", publie sur "order.approved" ou "order.rejected"
        -> ExecutionAgent écoute "order.approved", exécute, publie sur "trade.filled"
          -> PortfolioManager écoute "trade.filled", met à jour l'état
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
import logging

logger = logging.getLogger("message_bus")


@dataclass
class Message:
    topic: str
    payload: dict[str, Any]
    source: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


Handler = Callable[[Message], Awaitable[None]]


class MessageBus:
    """
    Bus pub/sub en mémoire (asyncio). Suffisant pour démarrer en local.
    Peut être remplacé plus tard par Redis pub/sub sans changer l'interface
    des agents (voir RedisMessageBus en bas de fichier, à activer pour du multi-process).
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)
        self._history: list[Message] = []  # utile pour audit/debug
        self._max_history = 5000

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subscribers[topic].append(handler)
        logger.debug(f"Nouvel abonné sur '{topic}': {handler.__qualname__}")

    async def publish(self, topic: str, payload: dict[str, Any], source: str) -> None:
        msg = Message(topic=topic, payload=payload, source=source)
        self._history.append(msg)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        logger.info(f"[{source}] -> '{topic}': {payload}")

        handlers = self._subscribers.get(topic, [])
        if not handlers:
            logger.debug(f"Aucun abonné pour le topic '{topic}'")
            return

        # On exécute tous les handlers en parallèle, mais on isole les erreurs
        # d'un agent pour ne pas faire tomber toute la firme.
        results = await asyncio.gather(
            *(self._safe_call(h, msg) for h in handlers),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Erreur dans un handler sur '{topic}': {r}")

    async def _safe_call(self, handler: Handler, msg: Message) -> None:
        try:
            await handler(msg)
        except Exception:
            logger.exception(f"Handler {handler.__qualname__} a échoué sur '{msg.topic}'")
            raise

    def recent_history(self, topic: str | None = None, limit: int = 50) -> list[Message]:
        msgs = self._history if topic is None else [m for m in self._history if m.topic == topic]
        return msgs[-limit:]
