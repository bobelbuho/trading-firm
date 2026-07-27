"""
Supervisor — le "CEO" de la firme. Démarre tous les agents, surveille
leur santé, et réagit aux événements critiques (kill-switch, échecs
d'exécution répétés, perte de connexion).
"""

import logging

from core.base_agent import BaseAgent
from core.message_bus import MessageBus, Message

logger = logging.getLogger("supervisor")


class Supervisor(BaseAgent):
    def __init__(self, bus: MessageBus) -> None:
        super().__init__(name="Supervisor", bus=bus)
        self._consecutive_failures = 0
        self._max_consecutive_failures = 5

    async def setup(self) -> None:
        self.bus.subscribe("firm.kill_switch", self._on_kill_switch)
        self.bus.subscribe("trade.failed", self._on_trade_failed)
        self.bus.subscribe("trade.filled", self._on_trade_success)
        self.bus.subscribe("portfolio.snapshot", self._on_snapshot)

    async def _on_kill_switch(self, msg: Message) -> None:
        self.logger.critical(f"ARRÊT D'URGENCE: {msg.payload['reason']}")
        # Ici tu peux ajouter: notification Slack/Telegram/email à l'équipe humaine

    async def _on_trade_failed(self, msg: Message) -> None:
        self._consecutive_failures += 1
        self.logger.error(f"Échec d'exécution #{self._consecutive_failures}: {msg.payload.get('error')}")
        if self._consecutive_failures >= self._max_consecutive_failures:
            await self.emit("firm.kill_switch", {
                "reason": f"{self._consecutive_failures} échecs d'exécution consécutifs — probable problème de connectivité broker"
            })

    async def _on_trade_success(self, msg: Message) -> None:
        self._consecutive_failures = 0

    async def _on_snapshot(self, msg: Message) -> None:
        p = msg.payload
        self.logger.info(
            f"Équity: {p['equity']:.2f} | Positions ouvertes: {p['open_positions']} | "
            f"PnL réalisé: {p['realized_pnl']:+.2f}"
        )
