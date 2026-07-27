"""
ExecutionAgent — envoie les ordres approuvés au broker et rapporte le résultat.

Rôle: recevoir "order.approved" du RiskManager, passer l'ordre réel (ou
simulé en mode paper), gérer le slippage/retry, et publier "trade.filled".

Le broker réel est injecté (interface OrderBroker) pour permettre le
paper trading ET le live avec le même code d'agent — seul le client
change.
"""

from typing import Protocol

from core.base_agent import BaseAgent
from core.message_bus import MessageBus, Message


class OrderBroker(Protocol):
    async def place_order(self, symbol: str, side: str, size: float,
                           stop_loss: float, take_profit: float) -> dict:
        """Doit retourner {order_id, fill_price, status}."""
        ...


class ExecutionAgent(BaseAgent):
    def __init__(self, bus: MessageBus, broker: OrderBroker, mode: str = "paper") -> None:
        super().__init__(name="ExecutionAgent", bus=bus)
        self.broker = broker
        self.mode = mode  # "paper" ou "live" — logué sur chaque trade pour audit
        self._kill_switch_active = False

    async def setup(self) -> None:
        self.bus.subscribe("order.approved", self._on_order_approved)
        self.bus.subscribe("firm.kill_switch", self._on_kill_switch)

    async def _on_kill_switch(self, msg: Message) -> None:
        self._kill_switch_active = True
        self.logger.critical(f"KILL-SWITCH ACTIVÉ: {msg.payload['reason']} — arrêt de toute exécution.")

    async def _on_order_approved(self, msg: Message) -> None:
        if self._kill_switch_active:
            self.logger.warning("Ordre ignoré: kill-switch actif.")
            return

        p = msg.payload
        try:
            result = await self.broker.place_order(
                symbol=p["symbol"],
                side=p["side"],
                size=p["size"],
                stop_loss=p["stop_loss"],
                take_profit=p["take_profit"],
                reference_price=p.get("price"),
            )
        except Exception as e:
            self.logger.error(f"Échec d'exécution sur {p['symbol']}: {e}")
            await self.emit("trade.failed", {**p, "error": str(e)})
            return

        await self.emit("trade.filled", {
            **p,
            "order_id": result["order_id"],
            "fill_price": result["fill_price"],
            "mode": self.mode,
        })
        self.logger.info(f"[{self.mode.upper()}] Ordre exécuté: {p['side']} {p['size']} {p['symbol']} @ {result['fill_price']}")
